"""CloudTrail read-only audit proof.

Uses CloudTrail **Event history** (free: last 90 days of management events, no
trail, no S3 bucket, no data events) to surface the exact API calls the agent
made during an incident. Presenting these as read-only (`Describe*`/`Get*`/
`List*`) is the secondary proof that the agent only inspected and never mutated.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.models import AuditCall
from config import Settings

logger = logging.getLogger("agentsentry.cloudtrail")

_READ_ONLY_PREFIXES = ("Describe", "Get", "List", "BatchGet", "Scan", "Query", "Lookup")


def _is_read_only(event_name: str) -> bool:
    return event_name.startswith(_READ_ONLY_PREFIXES)


class CloudTrailService:
    """Fetch the agent's recent management events for a given time window."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None if settings.use_mock_data else self._init_client()

    def _init_client(self):
        import boto3

        session = boto3.Session(
            aws_access_key_id=self._settings.aws_access_key_id,
            aws_secret_access_key=self._settings.aws_secret_access_key,
            aws_session_token=self._settings.aws_session_token,
            region_name=self._settings.region,
        )
        return session.client("cloudtrail")

    def get_agent_calls(
        self,
        since: datetime,
        until: datetime | None = None,
        principal: str | None = None,
    ) -> list[AuditCall]:
        """Return the agent's management events between ``since`` and ``until``.

        In mock mode the audit calls live on the seeded incidents, so this returns
        an empty list (the API serves the pre-seeded audit calls directly).
        """
        if self._settings.use_mock_data:
            return []

        principal = principal or self._settings.agent_iam_principal
        until = until or datetime.now(timezone.utc)

        calls: list[AuditCall] = []
        paginator = self._client.get_paginator("lookup_events")
        for page in paginator.paginate(
            LookupAttributes=[{"AttributeKey": "Username", "AttributeValue": principal}],
            StartTime=since,
            EndTime=until,
        ):
            for event in page.get("Events", []):
                name = event.get("EventName", "")
                calls.append(
                    AuditCall(
                        event_name=name,
                        event_time=event.get("EventTime", datetime.now(timezone.utc)),
                        aws_service=event.get("EventSource", "unknown"),
                        read_only=_is_read_only(name),
                        principal=principal,
                    )
                )
        return calls
