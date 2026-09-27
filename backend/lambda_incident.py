"""AWS Lambda entrypoint for the incident handler.

Invoked by EventBridge when a CloudWatch alarm enters the ALARM state. Writes a
PENDING incident record to DynamoDB so the dashboard shows it immediately and
the coding agent can pick it up for diagnosis.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core import configure_logging, get_container
from app.models import Incident, IncidentStatus, Severity

configure_logging()
logger = logging.getLogger("agentsentry.lambda.incident")


def _incident_from_alarm(detail: dict) -> Incident:
    """Build a PENDING incident from a CloudWatch Alarm State Change event."""
    alarm_name = detail.get("alarmName", "unknown-alarm")
    now = datetime.now(timezone.utc)
    # The monitored table is the demo victim; keep this mapping simple.
    resource_id = "agentsentry-monitored"
    incident_id = f"INC-{int(now.timestamp())}"
    return Incident(
        id=incident_id,
        title=f"DynamoDB throttling detected ({alarm_name})",
        resource_id=resource_id,
        resource_type="AWS::DynamoDB::Table",
        metric_name="ThrottledRequests",
        severity=Severity.HIGH,
        status=IncidentStatus.PENDING,
        diagnosis=None,
        detected_at=now,
        updated_at=now,
    )


def handler(event: dict, _context) -> dict:
    logger.info("Incident event received: %s", event.get("detail-type"))
    container = get_container()
    detail = event.get("detail", {})
    incident = _incident_from_alarm(detail)
    # Persist via the store (writes to DynamoDB in live mode).
    container.incident_store.save_incident(incident)
    logger.info("Stored incident %s (PENDING)", incident.id)
    return {"incidentId": incident.id, "status": incident.status.value}
