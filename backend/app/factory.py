"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audit, health, incidents, static_site, verification
from app.core import configure_logging, get_container


def create_app() -> FastAPI:
    configure_logging()
    container = get_container()

    app = FastAPI(
        title="AgentSentry AI",
        description="Autonomous DevSecOps & cloud infrastructure auto-remediation copilot.",
        version="1.0.0",
    )

    origins = container.settings.cors_origins_list
    allow_all = "*" in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins,
        # Credentials cannot be combined with a wildcard origin per the CORS spec.
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(incidents.router)
    app.include_router(verification.router)
    app.include_router(audit.router)
    # Registered last so the /api routers above take precedence; this one
    # serves the dashboard SPA from S3 over the API's HTTPS endpoint and owns
    # the catch-all route.
    app.include_router(static_site.router)

    return app
