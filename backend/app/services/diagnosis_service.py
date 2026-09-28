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
from .mcp_service import McpDocsService

logger = logging.getLogger("agentsentry.diagnosis")


class DiagnosisService:
    def __init__(
        self,
        settings: Settings,
        cloudwatch: CloudWatchService,
        docs: "McpDocsService | None" = None,
    ) -> None:
        self._settings = settings
        self._cw = cloudwatch
        self._docs = docs
        self._ddb = None if settings.use_mock_data else self._init_ddb()

    def consult_documentation(self, facts: dict) -> list[dict]:
        """Look up authoritative AWS guidance for the observed symptom.

        Uses the **AWS MCP Server (Agent Toolkit)** so the recommended fix is
        grounded in current AWS documentation rather than hardcoded advice.
        Returns [] if the lookup is unavailable — the pipeline still works.
        """
        if self._docs is None:
            return []
        billing = facts.get("billing_mode", "UNKNOWN")
        if billing == "PROVISIONED":
            phrase = (
                "DynamoDB ThrottledRequests provisioned write capacity exceeded "
                "switch to on-demand PAY_PER_REQUEST capacity mode best practice"
            )
        else:
            phrase = (
                "DynamoDB on-demand table throttling adaptive capacity warm-up "
                "exponential backoff retry throttled requests"
            )
        return self._docs.search_documentation(phrase, limit=3)

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

        # 15-minute window, summed: the real number of refused writes.
        throttled = self._cw.sum_metric(
            "AWS/DynamoDB", "ThrottledRequests", {"TableName": table_name, "Operation": "PutItem"}, 15
        )
        logger.info("observed %g throttled PutItem requests in 15 min for %s", throttled, table_name)
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
            rcu, wcu = facts["rcu"], facts["wcu"]
            # us-east-1 provisioned pricing: $0.00013/WCU-hr, $0.00013/RCU-hr
            # (~730 hrs/month). Free tier covers 25 RCU + 25 WCU.
            hours = 730
            before = round((wcu * 0.00065 + rcu * 0.00013) * hours, 2)
            # On-demand: $1.25 per million writes, $0.25 per million reads. At the
            # observed burst volume this is fractions of a cent, so we report the
            # small-but-nonzero estimate rather than a misleading $0.00.
            after = round(max(throttled, 1000) / 1_000_000 * 1.25, 2)

            diagnosis = (
                f"DynamoDB table `{table_name}` is rejecting writes because its provisioned write "
                f"capacity is too low for the traffic it is receiving.\n\n"
                f"Read-only inspection of the live table shows it is on **PROVISIONED** billing with "
                f"**{wcu} WCU** and **{rcu} RCU**. A single write consumes 1 WCU per KB, so {wcu} WCU "
                f"sustains only about {wcu} small {'write' if wcu == 1 else 'writes'} per second. "
                f"CloudWatch recorded "
                f"**{throttled:g} throttled `PutItem` requests in the last 15 minutes**, which means "
                f"real client writes were refused with `ProvisionedThroughputExceededException` once "
                f"the burst exceeded that ceiling.\n\n"
                f"This is a capacity-planning problem, not a code defect: the table's fixed capacity "
                f"cannot absorb spiky traffic."
            )
            impact = (
                "- **Data loss risk:** every throttled `PutItem` is a write that did not land. "
                "Clients without retry logic silently lose that data.\n"
                "- **User-visible errors:** throttling surfaces as 5xx/500 responses or failed "
                "operations in any service writing to this table.\n"
                "- **Recurrence:** the same burst pattern will throttle again, because nothing about "
                "the table's capacity changes on its own.\n"
                f"- **Observed blast radius:** {throttled:g} rejected writes in a 15-minute window."
            )
            why = (
                "Switching the table to **on-demand (`PAY_PER_REQUEST`)** billing removes the fixed "
                "ceiling entirely. DynamoDB then scales capacity automatically with traffic, so "
                "bursts are absorbed without anyone forecasting throughput. This is AWS's "
                "recommended mode for spiky or unpredictable workloads, and it eliminates the class "
                "of failure rather than just raising the limit."
            )
            alternatives = (
                f"| Option | Assessment |\n| --- | --- |\n"
                f"| **On-demand billing** (chosen) | Removes the capacity ceiling permanently; no "
                f"forecasting; scales with traffic. Best fit for bursty writes. |\n"
                f"| Raise provisioned WCU (e.g. {wcu} to {max(wcu * 5, 5)}) | Works only until traffic "
                f"exceeds the new ceiling; still requires ongoing capacity planning. |\n"
                f"| Enable auto-scaling on provisioned capacity | Helps for gradual ramps, but "
                f"reacts in minutes — too slow for sudden bursts like this one. |\n"
                f"| Client-side exponential backoff | Good defensive practice and complementary, but "
                f"it hides the problem rather than fixing the capacity shortfall. |"
            )
            verification = (
                "After this PR is merged and deployed, AgentSentry AI automatically re-reads the "
                f"live `ThrottledRequests` metric for `{table_name}` over a 5-minute window. The "
                "incident is only marked **RESOLVED_VERIFIED** if the metric has returned below "
                "threshold, and the observed value plus a timestamp are recorded. If throttling "
                "persists, the incident is marked **FAILED** instead — success is never assumed."
            )

            pr = PullRequest(
                number=0,
                url="",
                title=f"fix(ddb): switch {table_name} to on-demand billing to stop write throttling",
                branch="fix/agentsentry-remediation",
                cdk_diff=(
                    "Resources\n"
                    "[~] AWS::DynamoDB::Table MonitoredTable\n"
                    " ├─ [-] BillingMode: PROVISIONED\n"
                    f" ├─ [-] ProvisionedThroughput: {{ ReadCapacityUnits: {rcu}, WriteCapacityUnits: {wcu} }}\n"
                    " └─ [+] BillingMode: PAY_PER_REQUEST\n"
                    "\n"
                    "# infra/agentsentry/stack.py\n"
                    "- billing_mode=dynamodb.BillingMode.PROVISIONED,\n"
                    f"- read_capacity={rcu},\n"
                    f"- write_capacity={wcu},\n"
                    "+ billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,"
                ),
                rollback_plan=(
                    "Revert this commit and redeploy (`cdk deploy`) to restore `PROVISIONED` billing "
                    f"with RCU={rcu} / WCU={wcu}.\n\n"
                    "- Billing-mode changes are **non-destructive**: no data is moved or lost.\n"
                    "- No application code changes are required, so nothing else needs reverting.\n"
                    "- Note: AWS allows a billing-mode switch only once every 24 hours per table, so "
                    "an immediate re-revert may be rate-limited."
                ),
                cost_delta=CostDelta(before_monthly_usd=before, after_monthly_usd=after),
                opened_at=datetime.now(timezone.utc),
            )
            facts["_narrative"] = {
                "impact": impact,
                "why_this_fix": why,
                "alternatives": alternatives,
                "verification": verification,
            }
            return diagnosis, pr

        # Already on-demand — diagnose the throttle source honestly.
        diagnosis = (
            f"DynamoDB table `{table_name}` recorded **{throttled:g} throttled `PutItem` requests in "
            f"the last 15 minutes** despite already running on **{billing}** billing.\n\n"
            f"On-demand tables are not immune to throttling: DynamoDB provisions a starting capacity "
            f"and then grows it adaptively. If traffic more than doubles faster than the table's "
            f"adaptive capacity warms up, requests above the current ceiling are still refused with "
            f"`ProvisionedThroughputExceededException`. Because the billing mode is already correct, "
            f"the durable fix belongs on the client side: retry the rejected writes instead of "
            f"dropping them."
        )
        impact = (
            "- **Data loss risk:** throttled writes that are not retried are lost.\n"
            "- **Intermittent failures:** this appears as sporadic errors during traffic spikes, "
            "which is hard to reproduce and easy to misdiagnose.\n"
            f"- **Observed blast radius:** {throttled:g} rejected writes in a 15-minute window."
        )
        why = (
            "Because the table is already on-demand, raising capacity is not an available lever. "
            "Adding **exponential backoff with jitter** around writes makes the client tolerate the "
            "brief warm-up window: rejected writes are retried a few milliseconds later, by which "
            "point adaptive capacity has grown. This converts a hard failure into a short delay."
        )
        alternatives = (
            "| Option | Assessment |\n| --- | --- |\n"
            "| **Client-side exponential backoff + jitter** (chosen) | Directly prevents data loss; "
            "standard AWS SDK-recommended practice for throttling. |\n"
            "| Pre-warm the table with a gradual ramp | Effective before a known spike, but not "
            "possible for organic/unpredictable traffic. |\n"
            "| Batch writes (`BatchWriteItem`) | Reduces request count and helps, but does not "
            "remove throttling during a hard spike. |\n"
            "| Buffer writes through SQS | Most robust for extreme bursts, but adds a queue, latency "
            "and operational surface — disproportionate for this incident. |"
        )
        verification = (
            "After merge, AgentSentry AI re-reads the live `ThrottledRequests` metric over a 5-minute "
            "window and only records **RESOLVED_VERIFIED** if it has returned below threshold."
        )
        pr = PullRequest(
            number=0,
            url="",
            title=f"fix({table_name}): retry throttled writes with exponential backoff",
            branch="fix/agentsentry-remediation",
            cdk_diff=(
                "Application code\n"
                "[~] write path for " + table_name + "\n"
                " ├─ [+] wrap PutItem in exponential-backoff retry (max 5 attempts, jitter)\n"
                " └─ [+] emit a metric when a retry is exhausted (so loss is never silent)"
            ),
            rollback_plan=(
                "Revert this commit and redeploy. The change is confined to the client write path, "
                "is stateless, and touches no infrastructure or data — rollback is immediate and "
                "carries no migration risk."
            ),
            cost_delta=CostDelta(before_monthly_usd=0.0, after_monthly_usd=0.0),
            opened_at=datetime.now(timezone.utc),
        )
        facts["_narrative"] = {
            "impact": impact,
            "why_this_fix": why,
            "alternatives": alternatives,
            "verification": verification,
        }
        return diagnosis, pr
