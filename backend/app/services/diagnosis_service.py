"""Real, evidence-based diagnosis for a monitored resource.

This is the deterministic "agent brain" that runs inside the incident Lambda.
It performs **real read-only AWS inspection** (DescribeTable + CloudWatch
metrics), records the exact API calls it made (for the CloudTrail-style audit
trail), and produces a diagnosis + proposed Infrastructure-as-Code fix grounded
in the observed data — nothing hardcoded about the outcome.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models import AuditCall, CostDelta, PullRequest
from config import Settings

from .cloudwatch_service import CloudWatchService

logger = logging.getLogger("agentsentry.diagnosis")


class DiagnosisService:
    def __init__(self, settings: Settings, cloudwatch: CloudWatchService) -> None:
        self._settings = settings
        self._cw = cloudwatch
        self._ddb = None if settings.use_mock_data else self._init_ddb()

    def _init_ddb(self):
        import boto3

        session = boto3.Session(
            aws_access_key_id=self._settings.aws_access_key_id,
            aws_secret_access_key=self._settings.aws_secret_access_key,
            aws_session_token=self._settings.aws_session_token,
            region_name=self._settings.region,
        )
        return session.client("dynamodb")

    def inspect_table(self, table_name: str) -> dict:
        """Perform real read-only inspection of a DynamoDB table under throttling.

        Returns a dict with observed facts + the list of AuditCall records for
        every API call actually made.
        """
        principal = self._settings.agent_iam_principal
        calls: list[AuditCall] = []
        now = lambda: datetime.now(timezone.utc)  # noqa: E731

        billing_mode = "UNKNOWN"
        rcu = wcu = 0
        item_count = 0

        if not self._settings.use_mock_data and self._ddb is not None:
            desc = self._ddb.describe_table(TableName=table_name)
            calls.append(AuditCall(
                event_name="DescribeTable", event_time=now(),
                aws_service="dynamodb.amazonaws.com", read_only=True, principal=principal,
            ))
            t = desc["Table"]
            billing_mode = (t.get("BillingModeSummary", {}) or {}).get("BillingMode", "PROVISIONED")
            pt = t.get("ProvisionedThroughput", {}) or {}
            rcu = int(pt.get("ReadCapacityUnits", 0))
            wcu = int(pt.get("WriteCapacityUnits", 0))
            item_count = int(t.get("ItemCount", 0))

        throttled = self._cw.sum_metric(
            "AWS/DynamoDB", "ThrottledRequests", {"TableName": table_name, "Operation": "PutItem"}, 15
        )
        calls.append(AuditCall(
            event_name="GetMetricStatistics", event_time=now(),
            aws_service="monitoring.amazonaws.com", read_only=True, principal=principal,
        ))

        return {
            "billing_mode": billing_mode,
            "rcu": rcu,
            "wcu": wcu,
            "item_count": item_count,
            "throttled_15m": throttled,
            "audit_calls": calls,
        }

    def diagnose(self, table_name: str, facts: dict) -> tuple[str, PullRequest | None]:
        """Produce a diagnosis string + a proposed CDK fix from observed facts."""
        billing = facts["billing_mode"]
        throttled = facts["throttled_15m"]

        if billing == "PROVISIONED":
            diagnosis = (
                f"Live inspection of DynamoDB table '{table_name}' shows PROVISIONED billing "
                f"(RCU={facts['rcu']}, WCU={facts['wcu']}) with {throttled:g} throttled PutItem "
                f"requests in the last 15 minutes. Write bursts are exceeding provisioned write "
                f"capacity. Recommended fix: switch the table to on-demand (PAY_PER_REQUEST) "
                f"billing so it absorbs spiky traffic without manual capacity planning."
            )
            pr = PullRequest(
                number=0,
                url="",
                title=f"fix(ddb): switch {table_name} to on-demand billing",
                branch="fix/agentsentry-remediation",
                cdk_diff=(
                    "Resources\n"
                    "[~] AWS::DynamoDB::Table MonitoredTable\n"
                    " ├─ [-] BillingMode: PROVISIONED\n"
                    f" ├─ [-] ProvisionedThroughput: {{ RCU: {facts['rcu']}, WCU: {facts['wcu']} }}\n"
                    " └─ [+] BillingMode: PAY_PER_REQUEST"
                ),
                rollback_plan=(
                    "Revert the CDK change to restore PROVISIONED billing and redeploy. "
                    "Billing-mode changes are non-destructive; no data migration required."
                ),
                cost_delta=CostDelta(before_monthly_usd=0.0, after_monthly_usd=0.0),
                opened_at=datetime.now(timezone.utc),
            )
            return diagnosis, pr

        # Already on-demand (the default in our stack) — diagnose the throttle source honestly.
        diagnosis = (
            f"Live inspection of DynamoDB table '{table_name}' shows {billing} billing with "
            f"{throttled:g} throttled PutItem requests in the last 15 minutes. On-demand tables "
            f"can still throttle briefly when traffic ramps faster than the table's adaptive "
            f"capacity warms up. Recommended fix: enable/verify auto-scaling headroom and add a "
            f"brief client-side exponential backoff on writes to smooth the burst."
        )
        pr = PullRequest(
            number=0,
            url="",
            title=f"fix(ddb): add write backoff + capacity headroom for {table_name}",
            branch="fix/agentsentry-remediation",
            cdk_diff=(
                "Application code\n"
                "[~] writer.py\n"
                " └─ [+] wrap PutItem in exponential-backoff retry (max 5 attempts)"
            ),
            rollback_plan="Revert the writer change and redeploy. Stateless, instant rollback.",
            cost_delta=CostDelta(before_monthly_usd=0.0, after_monthly_usd=0.0),
            opened_at=datetime.now(timezone.utc),
        )
        return diagnosis, pr
