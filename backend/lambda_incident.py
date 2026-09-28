"""AWS Lambda entrypoint for the incident handler.

Invoked by EventBridge when a CloudWatch alarm enters the ALARM state. It:

  1. Reads the affected resource **from the alarm payload** — namespace, metric,
     statistic and the metric's full dimension set. Nothing about the resource is
     hardcoded, so pointing an alarm at another table, function or API routes
     through the same code path.
  2. Creates the incident record and stores that metric identity, so the later
     verification step re-reads exactly the metric that fired.
  3. Performs REAL read-only inspection and records every API call it made.
  4. Consults live AWS documentation through the AWS MCP Server (Agent Toolkit).
  5. Opens a real pull request against the repository that owns the affected
     resource's infrastructure code.

Nothing about the outcome is hardcoded: the diagnosis reflects live data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core import configure_logging, get_container
from app.models import Incident, IncidentStatus, Severity
from app.services.alarm_parser import parse_alarm_event

configure_logging()
logger = logging.getLogger("agentsentry.lambda.incident")


def handler(event: dict, _context) -> dict:
    logger.info("Incident event received: %s", event.get("detail-type"))
    container = get_container()
    settings = container.settings

    alarm = parse_alarm_event(event)
    if not alarm.is_supported:
        # Degrade rather than crash: record what we can so the alarm is visible.
        logger.warning(
            "Alarm %s is not a recognised resource (namespace=%r, dims=%s)",
            alarm.alarm_name, alarm.namespace, alarm.dimensions,
        )

    now = datetime.now(timezone.utc)
    incident_id = f"INC-{int(now.timestamp())}"
    resource_id = alarm.resource_id or alarm.alarm_name

    incident = Incident(
        id=incident_id,
        title=_title_for(alarm, resource_id),
        resource_id=resource_id,
        resource_type=alarm.resource_type,
        metric_name=alarm.metric_name or "Unknown",
        metric_namespace=alarm.namespace or None,
        metric_dimensions=alarm.dimensions,
        metric_statistic=alarm.statistic,
        alarm_name=alarm.alarm_name,
        severity=Severity.HIGH,
        status=IncidentStatus.DIAGNOSING,
        diagnosis=None,
        detected_at=now,
        updated_at=now,
    )
    # Persist immediately so the dashboard shows the incident the moment it fires.
    container.incident_store.save_incident(incident)
    logger.info(
        "Stored incident %s (DIAGNOSING) for %s %s",
        incident.id, incident.resource_type, incident.resource_id,
    )

    # Only resources we know how to reason about get a diagnosis and a PR.
    if alarm.namespace != "AWS/DynamoDB":
        logger.info(
            "No remediation rule for %s yet; incident recorded for review.",
            alarm.namespace or "unknown namespace",
        )
        return {"incidentId": incident.id, "status": incident.status.value}

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
            # Route the pull request to whichever repo owns this resource's IaC.
            repo = settings.repo_for_resource(resource_id)
            created = _maybe_open_pr(container, incident, pr, diagnosis, facts, repo)
            incident.pull_request = created or pr
            incident.status = IncidentStatus.PR_OPEN
        incident.updated_at = datetime.now(timezone.utc)
        container.incident_store.save_incident(incident)
        logger.info("Incident %s diagnosed -> %s", incident.id, incident.status.value)
    except Exception:  # noqa: BLE001 - keep the incident record even if inspection fails
        logger.exception("Diagnosis failed for %s; left in DIAGNOSING", incident.id)

    return {"incidentId": incident.id, "status": incident.status.value}


def _title_for(alarm, resource_id: str) -> str:
    """Human-readable title derived from the alarm, not a fixed string."""
    friendly = {
        "ThrottledRequests": "throttling detected",
        "Duration": "elevated duration",
        "5XXError": "elevated 5XX error rate",
        "Errors": "elevated error rate",
    }.get(alarm.metric_name, f"{alarm.metric_name or 'alarm'} breached")
    service = (alarm.namespace or "AWS").removeprefix("AWS/")
    return f"{service} {friendly} on {resource_id}"


def _maybe_open_pr(container, incident, pr, diagnosis: str, facts: dict, repo: str):
    """Create a real remediation branch + commit + PR when GitHub is configured."""
    gh = container.github.for_repo(repo)
    if not gh.configured:
        logger.info("GitHub not configured for %s; recording proposed fix only.", repo)
        return None

    logger.info("Opening remediation PR against %s", repo)
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
        f"| Alarm | `{incident.alarm_name}` |\n"
        f"| Breaching metric | `{incident.metric_namespace}/{incident.metric_name}` |\n"
        f"| Metric dimensions | `{incident.metric_dimensions}` |\n"
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
        + "\n\n---\n_Generated by AgentSentry AI from live read-only AWS inspection._\n"
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
