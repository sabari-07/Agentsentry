"""Verification endpoint — the primary proof loop.

Called (e.g. by a GitHub Actions "deploy complete" webhook) after a remediation
PR is merged and deployed. Re-checks the live metric and records the outcome.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core import Container, get_container
from app.models import Incident

router = APIRouter(prefix="/api/verification", tags=["verification"])


@router.post("/{incident_id}", response_model=Incident)
def verify_incident(incident_id: str, container: Container = Depends(get_container)) -> Incident:
    """Run the verification loop for an incident and return the updated record."""
    incident = container.verification.verify_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return incident
