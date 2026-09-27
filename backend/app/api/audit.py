"""Read-only audit endpoint — the secondary (CloudTrail) proof.

Surfaces the agent's management events for an incident so the dashboard can show
every call was read-only (Describe/Get/List). Sourced from free CloudTrail Event
history in live mode, or the incident's pre-seeded audit calls in mock mode.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core import Container, get_container
from app.models import AuditCall

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/{incident_id}", response_model=list[AuditCall])
def get_incident_audit(incident_id: str, container: Container = Depends(get_container)) -> list[AuditCall]:
    incident = container.incident_store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    # Mock mode: audit calls are attached to the incident.
    if container.settings.use_mock_data:
        return incident.audit_calls

    # Live mode: prefer real CloudTrail Event history for the incident window.
    calls = container.cloudtrail.get_agent_calls(
        since=incident.detected_at,
        until=incident.updated_at,
        principal=container.settings.agent_iam_principal,
    )
    # If CloudTrail has no matching events yet (e.g. right after seeding, before
    # real agent activity is recorded), fall back to the read-only calls stored
    # on the incident record so the audit panel still shows the evidence.
    if not calls and incident.audit_calls:
        return incident.audit_calls
    return calls
