"""Incident repository.

Abstracts persistence so the API does not care whether records come from an
in-memory mock (demo/dev) or a live DynamoDB table (production). The public
surface is identical in both modes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models import Incident, IncidentStatus, VerificationResult
from config import Settings

from .mock_data import build_seed_incidents

logger = logging.getLogger("agentsentry.incident_store")


class IncidentStore:
    """Read/update incidents from the backing store selected by settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._use_mock = settings.use_mock_data
        # In-memory cache keyed by incident id. Seeded in mock mode.
        self._incidents: dict[str, Incident] = {}

        if self._use_mock:
            for incident in build_seed_incidents(settings.agent_iam_principal):
                self._incidents[incident.id] = incident
            logger.info("IncidentStore running in MOCK mode with %d seed incidents", len(self._incidents))
        else:
            self._table = self._init_dynamo_table()
            logger.info("IncidentStore running in LIVE mode against table %s", settings.incident_table_name)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def list_incidents(self) -> list[Incident]:
        incidents = list(self._get_all().values())
        return sorted(incidents, key=lambda inc: inc.detected_at, reverse=True)

    def get_incident(self, incident_id: str) -> Incident | None:
        return self._get_all().get(incident_id)

    def save_incident(self, incident: Incident) -> Incident:
        """Create or update an incident record."""
        self._persist(incident)
        return incident

    def apply_verification(self, incident_id: str, result: VerificationResult) -> Incident | None:
        """Attach a verification result and move the incident to a terminal state."""
        incident = self.get_incident(incident_id)
        if incident is None:
            return None

        incident.verification = result
        incident.status = (
            IncidentStatus.RESOLVED_VERIFIED if result.healthy else IncidentStatus.FAILED
        )
        incident.updated_at = datetime.now(timezone.utc)
        self._persist(incident)
        return incident

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _get_all(self) -> dict[str, Incident]:
        if self._use_mock:
            return self._incidents
        return self._load_from_dynamo()

    def _persist(self, incident: Incident) -> None:
        if self._use_mock:
            self._incidents[incident.id] = incident
            return
        self._write_to_dynamo(incident)

    # --- DynamoDB (live mode) ---------------------------------------- #
    def _init_dynamo_table(self):
        import boto3  # local import so mock mode needs no AWS deps at runtime

        session = boto3.Session(
            aws_access_key_id=self._settings.aws_access_key_id,
            aws_secret_access_key=self._settings.aws_secret_access_key,
            aws_session_token=self._settings.aws_session_token,
            region_name=self._settings.region,
        )
        return session.resource("dynamodb").Table(self._settings.incident_table_name)

    def _load_from_dynamo(self) -> dict[str, Incident]:
        response = self._table.scan()
        incidents: dict[str, Incident] = {}
        for item in response.get("Items", []):
            try:
                incident = Incident.model_validate(item)
                incidents[incident.id] = incident
            except Exception:  # noqa: BLE001 - skip malformed rows, keep dashboard alive
                logger.exception("Skipping malformed incident row: %s", item.get("id"))
        return incidents

    def _write_to_dynamo(self, incident: Incident) -> None:
        # DynamoDB rejects Python floats; round-trip through JSON so numbers
        # become Decimals via parse_float.
        import json
        from decimal import Decimal

        item = json.loads(incident.model_dump_json(), parse_float=Decimal)
        self._table.put_item(Item=item)
