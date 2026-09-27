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
        diagnosis, pr = container.diagnosis.diagnose(resource_id, facts)
        incident.diagnosis = diagnosis
        incident.audit_calls = facts["audit_calls"]

        if pr is not None:
            # Optionally open a real GitHub PR when configured.
            created = _maybe_open_pr(container, pr)
            incident.pull_request = created or pr
            incident.status = IncidentStatus.PR_OPEN
        incident.updated_at = datetime.now(timezone.utc)
        container.incident_store.save_incident(incident)
        logger.info("Incident %s diagnosed -> %s", incident.id, incident.status.value)
    except Exception:  # noqa: BLE001 - keep the incident record even if inspection fails
        logger.exception("Diagnosis failed for %s; left in DIAGNOSING", incident.id)

    return {"incidentId": incident.id, "status": incident.status.value}


def _maybe_open_pr(container, pr):
    """Open a real GitHub PR if a token + repo are configured; else return None."""
    settings = container.settings
    if not settings.github_token or "your-org" in settings.github_repo:
        logger.info("GitHub not configured; recording proposed fix without opening a PR.")
        return None
    try:
        body = container.github.build_pr_body(
            diagnosis=pr.title, cdk_diff=pr.cdk_diff, cost_delta=pr.cost_delta, rollback=pr.rollback_plan
        )
        data = container.github.open_pull_request(title=pr.title, branch=pr.branch, body=body)
        if data:
            pr.number = data["number"]
            pr.url = data["html_url"]
            return pr
    except Exception:  # noqa: BLE001
        logger.exception("Failed to open GitHub PR; recording proposed fix only.")
    return None
