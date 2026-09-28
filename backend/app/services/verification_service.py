"""The verification loop — AgentSentry AI's primary proof.

After a remediation PR is merged and ``cdk deploy`` completes, this service
re-checks the incident's live metric over a short window. If the metric is back
under threshold, the incident is marked RESOLVED_VERIFIED with a timestamp;
otherwise FAILED. No claim of success is made without this check.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models import Incident, VerificationResult
from config import Settings

from .cloudwatch_service import CloudWatchService
from .incident_store import IncidentStore

logger = logging.getLogger("agentsentry.verification")

# A metric is considered healthy when its observed value is below this threshold.
_HEALTHY_THRESHOLD = 1.0


class VerificationService:
    def __init__(
        self,
        settings: Settings,
        store: IncidentStore,
        cloudwatch: CloudWatchService,
        github=None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._cloudwatch = cloudwatch
        self._github = github

    def verify_incident(self, incident_id: str) -> Incident | None:
        """Run the verification loop for a single incident and persist the result."""
        incident = self._store.get_incident(incident_id)
        if incident is None:
            logger.warning("Cannot verify unknown incident %s", incident_id)
            return None

        window = self._settings.verification_window_minutes
        observed = self._cloudwatch.get_metric_value(
            metric_name=incident.metric_name,
            resource_id=incident.resource_id,
            window_minutes=window,
        )
        healthy = observed < _HEALTHY_THRESHOLD

        summary = (
            f"{incident.metric_name} observed at {observed:g} "
            f"(threshold {_HEALTHY_THRESHOLD:g}) over {window} min after deploy — "
            f"{'healthy' if healthy else 'still breaching'}."
        )
        result = VerificationResult(
            metric_name=incident.metric_name,
            healthy=healthy,
            observed_value=observed,
            threshold=_HEALTHY_THRESHOLD,
            window_minutes=window,
            verified_at=datetime.now(timezone.utc),
            summary=summary,
        )
        logger.info("Verification for %s: %s", incident_id, summary)
        updated = self._store.apply_verification(incident_id, result)

        # Close the loop publicly: comment the measured outcome on the PR that
        # proposed the fix, so the evidence lives with the change.
        if updated is not None and self._github is not None and updated.pull_request:
            self._github.comment_verification(
                pr_number=updated.pull_request.number,
                verification=result,
                incident_id=incident_id,
            )
        return updated
