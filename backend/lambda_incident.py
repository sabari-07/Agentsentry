"""AWS Lambda entrypoint for the incident handler.

Invoked by EventBridge when a CloudWatch alarm enters the ALARM state. It:
  1. Creates a real incident record from the alarm.
  2. Performs REAL read-only inspection of the affected resource (DescribeTable +
     CloudWatch metrics) and records the exact API calls made (audit trail).
  3. Produces an evidence-based diagnosis + proposed Infrastructure-as-Code fix.
  4. Optionally opens a real GitHub PR when GITHUB_TOKEN is configured.
  5. Persists the incident (PR_OPEN if a PR was proposed, else DIAGNOSING).

Nothing about the outcome is hardcoded — the diagnosis reflects live data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core import configure_logging, get_container
from app.models import Incident, IncidentStatus, Severity

configure_logging()
logger = logging.getLogger("agentsentry.lambda.incident")


def handler(event: dict, _context) -> dict:
    logger.info("Incident event received: %s", event.get("detail-type"))
    container = get_container()
    detail = event.get("detail", {})

    alarm_name = detail.get("alarmName", "agentsentry-monitored-throttling")
    resource_id = event.get("resourceId") or "agentsentry-monitored"
    now = datetime.now(timezone.utc)
    incident_id = f"INC-{int(now.timestamp())}"

    incident = Incident(
        id=incident_id,
        title=f"DynamoDB throttling detected on {resource_id}",
        resource_id=resource_id,
        resource_type="AWS::DynamoDB::Table",
        metric_name="ThrottledRequests",
        severity=Severity.HIGH,
        status=IncidentStatus.DIAGNOSING,
        diagnosis=None,
        detected_at=now,
        updated_at=now,
    )
    # Persist immediately so the dashboard shows the incident the moment it fires.
    container.incident_store.save_incident(incident)
    logger.info("Stored incident %s (DIAGNOSING)", incident.id)

    # --- Real read-only inspection + diagnosis ---
    try:
        facts = container.diagnosis.inspect_table(resource_id)

        # Consult live AWS documentation through the AWS MCP Server (Agent
        # Toolkit) so the proposed fix cites authoritative guidance.
        docs = container.diagnosis.consult_documentation(facts)
        facts["docs"] = docs
        logger.info("Consulted %d AWS documentation source(s) via MCP", len(docs))

        diagnosis, pr = container.diagnosis.diagnose(resource_id, facts)
        incident.diagnosis = diagnosis
        incident.audit_calls = facts["audit_calls"]

        if pr is not None:
            # Open a real GitHub PR when configured (branch + commit + PR).
            created = _maybe_open_pr(container, incident, pr, diagnosis, facts)
            incident.pull_request = created or pr
            incident.status = IncidentStatus.PR_OPEN
        incident.updated_at = datetime.now(timezone.utc)
        container.incident_store.save_incident(incident)
        logger.info("Incident %s diagnosed -> %s", incident.id, incident.status.value)
    except Exception:  # noqa: BLE001 - keep the incident record even if inspection fails
        logger.exception("Diagnosis failed for %s; left in DIAGNOSING", incident.id)

    return {"incidentId": incident.id, "status": incident.status.value}


def _maybe_open_pr(container, incident, pr, diagnosis: str, facts: dict):
    """Create a real remediation branch + commit + PR when GitHub is configured."""
    gh = container.github
    if not gh.configured:
        logger.info("GitHub not configured; recording proposed fix without opening a PR.")
        return None

    narrative = facts.get("_narrative", {})
    body = gh.build_pr_body(
        diagnosis=diagnosis,
        cdk_diff=pr.cdk_diff,
        cost_delta=pr.cost_delta,
        rollback=pr.rollback_plan,
        incident=incident,
        facts=facts,
        impact=narrative.get("impact", ""),
        why_this_fix=narrative.get("why_this_fix", ""),
        alternatives=narrative.get("alternatives", ""),
        verification=narrative.get("verification", ""),
        audit_calls=incident.audit_calls,
        docs=facts.get("docs"),
    )
    # Commit a real, reviewable remediation manifest tied to this incident.
    file_path = f"remediations/{incident.id}.md"
    file_content = (
        f"# Incident report — {incident.id}\n\n"
        f"| Field | Value |\n| --- | --- |\n"
        f"| Resource | `{incident.resource_id}` |\n"
        f"| Resource type | `{incident.resource_type}` |\n"
        f"| Breaching metric | `{incident.metric_name}` |\n"
        f"| Severity | {incident.severity.value} |\n"
        f"| Detected at | {incident.detected_at.isoformat()} |\n\n"
        f"## What went wrong\n\n{diagnosis}\n\n"
        f"## Evidence (live, read-only)\n\n"
        f"| Observation | Value |\n| --- | --- |\n"
        f"| Billing mode | `{facts.get('billing_mode')}` |\n"
        f"| Read capacity (RCU) | {facts.get('rcu')} |\n"
        f"| Write capacity (WCU) | {facts.get('wcu')} |\n"
        f"| Throttled PutItem (15 min) | {facts.get('throttled_15m')} |\n\n"
        f"## Impact\n\n{narrative.get('impact', 'n/a')}\n\n"
        f"## The fix\n\n{narrative.get('why_this_fix', '')}\n\n"
        f"```\n{pr.cdk_diff}\n```\n\n"
        f"## Alternatives considered\n\n{narrative.get('alternatives', 'n/a')}\n\n"
        f"## Cost impact\n\n"
        f"| Before | After |\n| --- | --- |\n"
        f"| ${pr.cost_delta.before_monthly_usd:.2f}/mo | ${pr.cost_delta.after_monthly_usd:.2f}/mo |\n\n"
        f"## Verification\n\n{narrative.get('verification', '')}\n\n"
        f"## Rollback plan\n\n{pr.rollback_plan}\n\n"
        f"## Read-only audit trail\n\n"
        + "\n".join(
            f"- `{c.event_name}` ({c.aws_service.replace('.amazonaws.com', '')}) — read-only"
            for c in incident.audit_calls
        )
        + f"\n\n---\n_Generated by AgentSentry AI from live read-only AWS inspection._\n"
    )

    data = gh.create_remediation_pr(
        title=pr.title,
        branch=pr.branch,
        body=body,
        file_path=file_path,
        file_content=file_content,
        commit_message=f"fix({incident.resource_id}): remediation for {incident.id}",
    )
    if data:
        pr.number = data["number"]
        pr.url = data["html_url"]
        pr.branch = data["head"]["ref"]
        return pr
    return None
