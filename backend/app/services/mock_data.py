"""Realistic seed data used when ``USE_MOCK_DATA=true``.

This lets the dashboard run end-to-end (and demo cleanly) without live AWS
resources, while mirroring the exact shapes the real AWS services return.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import (
    AuditCall,
    CostDelta,
    Incident,
    IncidentStatus,
    PullRequest,
    Severity,
    VerificationResult,
)

_NOW = datetime.now(timezone.utc)


def _read_only_calls(principal: str, service: str, names: list[str], base: datetime) -> list[AuditCall]:
    return [
        AuditCall(
            event_name=name,
            event_time=base + timedelta(seconds=15 * i),
            aws_service=service,
            read_only=True,
            principal=principal,
        )
        for i, name in enumerate(names)
    ]


def build_seed_incidents(principal: str = "agentsentry-agent") -> list[Incident]:
    """Return a small, story-driven set of incidents across the full lifecycle."""

    # 1) A fully resolved & verified incident — the "hero" demo path.
    resolved = Incident(
        id="INC-1001",
        title="DynamoDB throttling on agentsentry-incidents",
        resource_id="agentsentry-incidents",
        resource_type="AWS::DynamoDB::Table",
        metric_name="ThrottledRequests",
        severity=Severity.HIGH,
        status=IncidentStatus.RESOLVED_VERIFIED,
        diagnosis=(
            "Write bursts exceeded provisioned WCU, causing ThrottledRequests to spike. "
            "Recommended switching the table to on-demand (PAY_PER_REQUEST) billing to "
            "absorb spiky traffic without capacity planning."
        ),
        detected_at=_NOW - timedelta(hours=3),
        updated_at=_NOW - timedelta(hours=2, minutes=40),
        pull_request=PullRequest(
            number=42,
            url="https://github.com/your-org/agentsentry-ai/pull/42",
            title="fix(ddb): switch agentsentry-incidents to on-demand billing",
            branch="fix/agentsentry-remediation-1001",
            cdk_diff=(
                "Resources\n"
                "[~] AWS::DynamoDB::Table IncidentTable\n"
                " ├─ [-] BillingMode: PROVISIONED\n"
                " ├─ [-] ProvisionedThroughput: { ReadCapacityUnits: 5, WriteCapacityUnits: 5 }\n"
                " └─ [+] BillingMode: PAY_PER_REQUEST"
            ),
            rollback_plan=(
                "Revert the CDK change to restore PROVISIONED billing with RCU/WCU = 5/5 and "
                "redeploy. No data migration required; billing mode changes are non-destructive."
            ),
            cost_delta=CostDelta(before_monthly_usd=0.00, after_monthly_usd=0.00),
            opened_at=_NOW - timedelta(hours=2, minutes=55),
        ),
        verification=VerificationResult(
            metric_name="ThrottledRequests",
            healthy=True,
            observed_value=0.0,
            threshold=1.0,
            window_minutes=5,
            verified_at=_NOW - timedelta(hours=2, minutes=40),
            summary="ThrottledRequests held at 0 for 5 consecutive minutes after deploy.",
        ),
        audit_calls=_read_only_calls(
            principal,
            "dynamodb.amazonaws.com",
            ["DescribeTable", "GetMetricData", "DescribeStacks", "GetMetricStatistics"],
            _NOW - timedelta(hours=2, minutes=58),
        ),
    )

    # 2) A PR awaiting human merge — shows the "PR as hero" artifact.
    pr_open = Incident(
        id="INC-1002",
        title="Lambda incident-handler approaching timeout",
        resource_id="agentsentry-incident-handler",
        resource_type="AWS::Lambda::Function",
        metric_name="Duration",
        severity=Severity.MEDIUM,
        status=IncidentStatus.PR_OPEN,
        diagnosis=(
            "p99 Duration is trending toward the 3000ms timeout under load. Real duration "
            "percentiles indicate the function is memory-bound; raising memory also raises CPU."
        ),
        detected_at=_NOW - timedelta(minutes=35),
        updated_at=_NOW - timedelta(minutes=20),
        pull_request=PullRequest(
            number=43,
            url="https://github.com/your-org/agentsentry-ai/pull/43",
            title="fix(lambda): raise incident-handler memory 128MB -> 256MB",
            branch="fix/agentsentry-remediation-1002",
            cdk_diff=(
                "Resources\n"
                "[~] AWS::Lambda::Function IncidentHandler\n"
                " ├─ [-] MemorySize: 128\n"
                " └─ [+] MemorySize: 256"
            ),
            rollback_plan="Revert MemorySize to 128 and redeploy. Stateless change, instant rollback.",
            cost_delta=CostDelta(before_monthly_usd=0.00, after_monthly_usd=0.00),
            opened_at=_NOW - timedelta(minutes=20),
        ),
        audit_calls=_read_only_calls(
            principal,
            "lambda.amazonaws.com",
            ["GetFunctionConfiguration", "GetMetricData", "DescribeStacks"],
            _NOW - timedelta(minutes=30),
        ),
    )

    # 3) A freshly detected incident being diagnosed.
    diagnosing = Incident(
        id="INC-1003",
        title="API Gateway 5XX error rate elevated",
        resource_id="agentsentry-api",
        resource_type="AWS::ApiGateway::RestApi",
        metric_name="5XXError",
        severity=Severity.HIGH,
        status=IncidentStatus.DIAGNOSING,
        diagnosis=None,
        detected_at=_NOW - timedelta(minutes=4),
        updated_at=_NOW - timedelta(minutes=3),
        audit_calls=_read_only_calls(
            principal,
            "apigateway.amazonaws.com",
            ["GetRestApi", "GetMetricData"],
            _NOW - timedelta(minutes=3),
        ),
    )

    return [diagnosing, pr_open, resolved]
