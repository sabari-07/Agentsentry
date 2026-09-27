"""Incident and remediation-PR endpoints that feed the dashboard columns."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core import Container, get_container
from app.models import Incident, IncidentStatus

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=list[Incident])
def list_incidents(container: Container = Depends(get_container)) -> list[Incident]:
    """All incidents, newest first (drives every dashboard column)."""
    return container.incident_store.list_incidents()


@router.get("/active", response_model=list[Incident])
def list_active(container: Container = Depends(get_container)) -> list[Incident]:
    """Incidents that are still open (detected / diagnosing)."""
    active = {IncidentStatus.PENDING, IncidentStatus.DIAGNOSING}
    return [inc for inc in container.incident_store.list_incidents() if inc.status in active]


@router.get("/open-prs", response_model=list[Incident])
def list_open_prs(container: Container = Depends(get_container)) -> list[Incident]:
    """Incidents whose remediation PR is open and awaiting a human merge."""
    return [
        inc
        for inc in container.incident_store.list_incidents()
        if inc.status in {IncidentStatus.PR_OPEN, IncidentStatus.DEPLOYING} and inc.pull_request
    ]


@router.get("/resolved", response_model=list[Incident])
def list_resolved(container: Container = Depends(get_container)) -> list[Incident]:
    """Incidents with a verified resolution — the proof column."""
    return [
        inc
        for inc in container.incident_store.list_incidents()
        if inc.status == IncidentStatus.RESOLVED_VERIFIED
    ]


@router.get("/{incident_id}", response_model=Incident)
def get_incident(incident_id: str, container: Container = Depends(get_container)) -> Incident:
    incident = container.incident_store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return incident
