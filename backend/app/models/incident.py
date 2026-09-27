"""Domain models for incidents, remediation PRs, verification and audit."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class IncidentStatus(str, Enum):
    """Lifecycle of an incident as it moves through the remediation pipeline."""

    PENDING = "PENDING"          # detected, awaiting agent diagnosis
    DIAGNOSING = "DIAGNOSING"    # agent inspecting via read-only MCP calls
    PR_OPEN = "PR_OPEN"          # remediation PR opened, awaiting human merge
    DEPLOYING = "DEPLOYING"      # PR merged, cdk deploy running
    RESOLVED_VERIFIED = "RESOLVED_VERIFIED"  # metric re-checked and confirmed healthy
    FAILED = "FAILED"            # verification did not confirm a fix


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CostDelta(BaseModel):
    """Before/after cost estimate attached to a remediation PR."""

    before_monthly_usd: float = Field(..., ge=0)
    after_monthly_usd: float = Field(..., ge=0)
    currency: str = "USD"

    @property
    def difference_usd(self) -> float:
        return round(self.after_monthly_usd - self.before_monthly_usd, 2)


class PullRequest(BaseModel):
    """A remediation Pull Request opened by the agent."""

    number: int
    url: str
    title: str
    branch: str
    cdk_diff: str
    rollback_plan: str
    cost_delta: CostDelta
    opened_at: datetime


class AuditCall(BaseModel):
    """A single CloudTrail management event made by the agent (read-only proof)."""

    event_name: str          # e.g. DescribeTable, GetMetricData, ListStacks
    event_time: datetime
    aws_service: str         # e.g. dynamodb.amazonaws.com
    read_only: bool
    principal: str


class VerificationResult(BaseModel):
    """Outcome of the post-deploy verification loop."""

    metric_name: str
    healthy: bool
    observed_value: float
    threshold: float
    window_minutes: int
    verified_at: datetime
    summary: str


class Incident(BaseModel):
    """The central record threaded through the whole pipeline."""

    id: str
    title: str
    resource_id: str          # e.g. the DynamoDB table name
    resource_type: str        # e.g. AWS::DynamoDB::Table
    metric_name: str          # e.g. ThrottledRequests
    severity: Severity
    status: IncidentStatus
    diagnosis: str | None = None
    detected_at: datetime
    updated_at: datetime
    pull_request: PullRequest | None = None
    verification: VerificationResult | None = None
    audit_calls: list[AuditCall] = Field(default_factory=list)
