"""AWS Lambda entrypoint for the verification handler (the primary proof loop).

Invoked by the GitHub Actions "deploy complete" step after a remediation PR is
merged and deployed. Re-checks the incident's live CloudWatch metric and marks
it RESOLVED_VERIFIED (or FAILED) with a timestamp.

Event shape: {"incidentId": "INC-..."}
"""
from __future__ import annotations

import logging

from app.core import configure_logging, get_container

configure_logging()
logger = logging.getLogger("agentsentry.lambda.verify")


def handler(event: dict, _context) -> dict:
    incident_id = event.get("incidentId")
    if not incident_id:
        logger.error("No incidentId in event: %s", event)
        return {"error": "incidentId is required"}

    container = get_container()
    incident = container.verification.verify_incident(incident_id)
    if incident is None:
        return {"error": f"incident {incident_id} not found"}

    logger.info("Verification complete for %s: %s", incident_id, incident.status.value)
    return {
        "incidentId": incident.id,
        "status": incident.status.value,
        "verified": incident.verification.healthy if incident.verification else None,
    }
