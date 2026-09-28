"""Tests for the verification loop — the component that must be able to fail.

The central claim of this project is that a fix is only reported as working when
the live metric says so. A verification step that can only return success is
indistinguishable from no verification at all, so these tests assert both
outcomes and that the failing path is reachable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import Incident, IncidentStatus, Severity
from app.services.verification_service import VerificationService
from config import Settings


def _settings() -> Settings:
    return Settings(use_mock_data=True, verification_window_minutes=5)


def _incident(status=IncidentStatus.PR_OPEN) -> Incident:
    now = datetime.now(timezone.utc)
    return Incident(
        id="INC-TEST",
        title="DynamoDB throttling",
        resource_id="agentsentry-monitored",
        resource_type="AWS::DynamoDB::Table",
        metric_name="ThrottledRequests",
        severity=Severity.HIGH,
        status=status,
        detected_at=now,
        updated_at=now,
    )


class _Store:
    def __init__(self, incident: Incident | None):
        self.incident = incident
        self.applied = None

    def get_incident(self, _id):
        return self.incident

    def apply_verification(self, _id, result):
        self.applied = result
        self.incident.verification = result
        self.incident.status = (
            IncidentStatus.RESOLVED_VERIFIED if result.healthy else IncidentStatus.FAILED
        )
        return self.incident


class _CW:
    def __init__(self, value: float):
        self.value = value

    def get_metric_value(self, **_kwargs):
        return self.value


class _GitHub:
    def __init__(self):
        self.comments: list[tuple[int, bool]] = []

    def comment_verification(self, pr_number, verification, incident_id):  # noqa: ARG002
        self.comments.append((pr_number, verification.healthy))
        return True


# --------------------------------------------------------------------------- #
# Both outcomes must be reachable
# --------------------------------------------------------------------------- #
def test_breaching_metric_marks_incident_failed():
    """116 refused writes must NOT be reported as a successful fix."""
    store = _Store(_incident())
    svc = VerificationService(_settings(), store, _CW(116.0))

    result = svc.verify_incident("INC-TEST")

    assert result.status == IncidentStatus.FAILED
    assert result.verification.healthy is False
    assert result.verification.observed_value == 116.0
    assert "still breaching" in result.verification.summary


def test_recovered_metric_marks_incident_verified():
    store = _Store(_incident())
    svc = VerificationService(_settings(), store, _CW(0.0))

    result = svc.verify_incident("INC-TEST")

    assert result.status == IncidentStatus.RESOLVED_VERIFIED
    assert result.verification.healthy is True
    assert result.verification.observed_value == 0.0
    assert "healthy" in result.verification.summary


def test_value_exactly_at_threshold_is_not_healthy():
    """Threshold is exclusive: a single refused write is still a breach."""
    store = _Store(_incident())
    svc = VerificationService(_settings(), store, _CW(1.0))

    result = svc.verify_incident("INC-TEST")
    assert result.status == IncidentStatus.FAILED


def test_verification_records_the_observation_window_and_timestamp():
    store = _Store(_incident())
    svc = VerificationService(_settings(), store, _CW(0.0))

    v = svc.verify_incident("INC-TEST").verification
    assert v.window_minutes == 5
    assert v.verified_at.tzinfo is not None, "timestamp must be timezone-aware"


def test_unknown_incident_returns_none_without_crashing():
    svc = VerificationService(_settings(), _Store(None), _CW(0.0))
    assert svc.verify_incident("INC-MISSING") is None


# --------------------------------------------------------------------------- #
# The result is published back to the pull request
# --------------------------------------------------------------------------- #
def test_failure_is_reported_on_the_pull_request():
    """A negative result must be published, not quietly dropped."""
    from app.models import CostDelta, PullRequest

    incident = _incident()
    incident.pull_request = PullRequest(
        number=5, url="https://example.com/pull/5", title="fix",
        branch="fix/x", cdk_diff="", rollback_plan="",
        cost_delta=CostDelta(before_monthly_usd=0.57, after_monthly_usd=0.0),
        opened_at=datetime.now(timezone.utc),
    )
    gh = _GitHub()
    svc = VerificationService(_settings(), _Store(incident), _CW(116.0), gh)

    svc.verify_incident("INC-TEST")

    assert gh.comments == [(5, False)], "the failing verdict must reach the PR"


def test_incident_without_pr_skips_commenting():
    gh = _GitHub()
    svc = VerificationService(_settings(), _Store(_incident()), _CW(0.0), gh)
    svc.verify_incident("INC-TEST")
    assert gh.comments == []
