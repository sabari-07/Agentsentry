"""Tests for CloudWatch metric querying.

These exist because of a real bug: the verification loop queried
``ThrottledRequests`` with only the ``TableName`` dimension. CloudWatch
identifies a metric by its COMPLETE dimension set, so the query matched nothing,
returned zero datapoints, and the loop reported "healthy" for a metric it had
never actually read — a silent false positive in the one component whose job is
to be trustworthy.

The same query also used ``Maximum``. DynamoDB emits each throttle as a separate
event of value 1, so Maximum is always 1 when any throttling occurs and says
nothing about volume. ``Sum`` is the real count of refused requests.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.cloudwatch_service import _METRIC_SPECS, CloudWatchService
from config import Settings


def _settings(**overrides) -> Settings:
    base = dict(use_mock_data=True, aws_region="us-east-1")
    base.update(overrides)
    return Settings(**base)


class _FakeCloudWatch:
    """Records the query it was given and returns canned datapoints."""

    def __init__(self, datapoints: list[dict]):
        self._datapoints = datapoints
        self.last_kwargs: dict | None = None

    def get_metric_statistics(self, **kwargs):
        self.last_kwargs = kwargs
        return {"Datapoints": self._datapoints}


def _live_service(datapoints: list[dict]) -> tuple[CloudWatchService, _FakeCloudWatch]:
    svc = CloudWatchService(_settings(use_mock_data=True))
    fake = _FakeCloudWatch(datapoints)
    # Force live behaviour with an injected client.
    svc._settings = _settings(use_mock_data=False)  # noqa: SLF001
    svc._client = fake  # noqa: SLF001
    return svc, fake


# --------------------------------------------------------------------------- #
# Dimension completeness — the actual bug
# --------------------------------------------------------------------------- #
def test_throttled_requests_includes_operation_dimension():
    """Regression: querying TableName alone matches no metric and returns 0."""
    svc = CloudWatchService(_settings())
    dims = svc.build_dimensions("ThrottledRequests", "my-table")
    names = {d["Name"] for d in dims}

    assert "TableName" in names
    assert "Operation" in names, (
        "ThrottledRequests is published per operation; omitting the Operation "
        "dimension silently matches nothing and fakes a healthy result."
    )
    assert {"Name": "TableName", "Value": "my-table"} in dims


def test_throttled_requests_uses_sum_not_maximum():
    """Maximum is always 1 for this metric, so it cannot express volume."""
    assert _METRIC_SPECS["ThrottledRequests"]["statistic"] == "Sum"


def test_unsupported_metric_raises_rather_than_silently_passing():
    svc = CloudWatchService(_settings())
    with pytest.raises(ValueError):
        svc.build_dimensions("NotARealMetric", "my-table")


def test_dimensions_are_passed_through_to_the_api_call():
    svc, fake = _live_service([{"Sum": 5.0}])
    svc.get_metric_value("ThrottledRequests", "my-table", 5)

    sent = {d["Name"]: d["Value"] for d in fake.last_kwargs["Dimensions"]}
    assert sent == {"TableName": "my-table", "Operation": "PutItem"}
    assert fake.last_kwargs["Statistics"] == ["Sum"]
    assert fake.last_kwargs["Namespace"] == "AWS/DynamoDB"


# --------------------------------------------------------------------------- #
# Value aggregation
# --------------------------------------------------------------------------- #
def test_sum_metric_totals_every_datapoint():
    """116 refused writes across two minutes must report 116, not 1."""
    svc, _ = _live_service([{"Sum": 64.0}, {"Sum": 52.0}])
    assert svc.get_metric_value("ThrottledRequests", "my-table", 5) == 116.0


def test_maximum_statistic_takes_the_peak():
    svc, _ = _live_service([{"Maximum": 900.0}, {"Maximum": 2400.0}])
    assert svc.get_metric_value("Duration", "my-fn", 5) == 2400.0


def test_no_datapoints_reports_zero():
    svc, _ = _live_service([])
    assert svc.get_metric_value("ThrottledRequests", "my-table", 5) == 0.0


def test_mock_mode_never_calls_aws():
    svc = CloudWatchService(_settings(use_mock_data=True))
    assert svc.get_metric_value("ThrottledRequests", "my-table", 5) == 0.0


def test_sum_metric_helper_matches_requested_dimensions():
    svc, fake = _live_service([{"Sum": 21.0}])
    total = svc.sum_metric(
        "AWS/DynamoDB", "ThrottledRequests",
        {"TableName": "t", "Operation": "PutItem"}, 15,
    )
    assert total == 21.0
    assert {d["Name"] for d in fake.last_kwargs["Dimensions"]} == {"TableName", "Operation"}


def test_window_minutes_controls_the_time_range():
    svc, fake = _live_service([{"Sum": 1.0}])
    svc.get_metric_value("ThrottledRequests", "my-table", 5)
    start = fake.last_kwargs["StartTime"]
    end = fake.last_kwargs["EndTime"]
    assert isinstance(start, datetime) and isinstance(end, datetime)
    minutes = round((end - start).total_seconds() / 60)
    assert minutes == 5
    assert end <= datetime.now(timezone.utc)
