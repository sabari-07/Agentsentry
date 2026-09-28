"""CloudWatch access for the verification loop.

Reads a single metric over a short window to confirm an incident's metric has
returned to healthy after a remediation deploy. All calls are read-only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config import Settings

logger = logging.getLogger("agentsentry.cloudwatch")

# How to query each verifiable metric.
#
# IMPORTANT: a CloudWatch metric is identified by its COMPLETE dimension set. A
# partial set matches nothing and silently returns zero datapoints, which would
# make verification report "healthy" for a metric it never actually read.
# DynamoDB publishes ThrottledRequests per operation, so the Operation dimension
# is required — querying TableName alone returns no data.
#
# `statistic` matters too: ThrottledRequests is emitted as individual events of
# value 1, so Maximum is always 1 when any throttling occurs and tells us
# nothing about volume. Sum gives the real number of refused requests.
_METRIC_SPECS: dict[str, dict] = {
    "ThrottledRequests": {
        "namespace": "AWS/DynamoDB",
        "primary_dimension": "TableName",
        "extra_dimensions": {"Operation": "PutItem"},
        "statistic": "Sum",
    },
    "Duration": {
        "namespace": "AWS/Lambda",
        "primary_dimension": "FunctionName",
        "extra_dimensions": {},
        "statistic": "Maximum",
    },
    "5XXError": {
        "namespace": "AWS/ApiGateway",
        "primary_dimension": "ApiName",
        "extra_dimensions": {},
        "statistic": "Sum",
    },
}


class CloudWatchService:
    """Fetch metric statistics for verification."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None if settings.use_mock_data else self._init_client()

    def _init_client(self):
        import boto3

        session = boto3.Session(
            aws_access_key_id=self._settings.aws_access_key_id,
            aws_secret_access_key=self._settings.aws_secret_access_key,
            aws_session_token=self._settings.aws_session_token,
            region_name=self._settings.region,
        )
        return session.client("cloudwatch")

    def build_dimensions(self, metric_name: str, resource_id: str) -> list[dict]:
        """Build the COMPLETE dimension set required to match the metric."""
        spec = _METRIC_SPECS.get(metric_name)
        if spec is None:
            raise ValueError(f"Unsupported metric for verification: {metric_name}")
        dims = [{"Name": spec["primary_dimension"], "Value": resource_id}]
        dims += [{"Name": k, "Value": v} for k, v in spec["extra_dimensions"].items()]
        return dims

    def get_metric_value(self, metric_name: str, resource_id: str, window_minutes: int) -> float:
        """Return the observed value of ``metric_name`` over the window.

        Uses the metric's correct full dimension set and statistic. A genuinely
        absent metric (no datapoints) means the condition is not occurring, which
        is the healthy case; but the dimension set must be right or "no data"
        would be indistinguishable from "recovered".

        In mock mode this returns 0.0 (healthy) so the loop can be demoed without
        live infrastructure.
        """
        if self._settings.use_mock_data:
            logger.info("[mock] metric %s for %s -> 0.0", metric_name, resource_id)
            return 0.0

        spec = _METRIC_SPECS[metric_name]
        statistic = spec["statistic"]
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=window_minutes)

        response = self._client.get_metric_statistics(
            Namespace=spec["namespace"],
            MetricName=metric_name,
            Dimensions=self.build_dimensions(metric_name, resource_id),
            StartTime=start,
            EndTime=end,
            Period=60,
            Statistics=[statistic],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            logger.info(
                "metric %s for %s: no datapoints in last %d min -> treating as 0",
                metric_name, resource_id, window_minutes,
            )
            return 0.0

        if statistic == "Sum":
            value = sum(dp["Sum"] for dp in datapoints)
        else:
            value = max(dp[statistic] for dp in datapoints)
        logger.info(
            "metric %s for %s: %s=%g over %d datapoint(s)",
            metric_name, resource_id, statistic, value, len(datapoints),
        )
        return float(value)

    def sum_metric(self, namespace: str, metric_name: str, dimensions: dict, minutes: int) -> float:
        """Return the summed value of a metric over the last ``minutes`` (read-only)."""
        if self._settings.use_mock_data or self._client is None:
            return 0.0
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        resp = self._client.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=[{"Name": k, "Value": v} for k, v in dimensions.items()],
            StartTime=start,
            EndTime=end,
            Period=60,
            Statistics=["Sum"],
        )
        pts = resp.get("Datapoints", [])
        return sum(p["Sum"] for p in pts) if pts else 0.0
