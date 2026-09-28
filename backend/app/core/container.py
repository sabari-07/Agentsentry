"""Lightweight dependency container.

Instantiates services once and exposes them to FastAPI routes via dependency
functions. Keeps wiring in one place and out of the route handlers.
"""
from __future__ import annotations

from functools import lru_cache

from app.services import (
    CloudTrailService,
    CloudWatchService,
    DiagnosisService,
    GitHubService,
    IncidentStore,
    McpDocsService,
    ReasoningService,
    VerificationService,
)
from config import Settings, get_settings


class Container:
    """Holds singleton service instances for the app's lifetime."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.incident_store = IncidentStore(settings)
        self.cloudwatch = CloudWatchService(settings)
        self.cloudtrail = CloudTrailService(settings)
        self.github = GitHubService(settings)
        self.mcp_docs = McpDocsService(settings)
        self.reasoning = ReasoningService(settings)
        self.diagnosis = DiagnosisService(
            settings, self.cloudwatch, self.mcp_docs, self.reasoning
        )
        self.verification = VerificationService(
            settings, self.incident_store, self.cloudwatch, self.github
        )


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
