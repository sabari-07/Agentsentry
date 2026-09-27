"""AWS Lambda entrypoint for the FastAPI dashboard API.

Wraps the same FastAPI app used locally with Mangum so API Gateway (HTTP API)
can invoke it. Single source of truth for the API — no duplicated logic.
"""
from __future__ import annotations

from mangum import Mangum

from app.factory import create_app

app = create_app()
handler = Mangum(app, lifespan="off")
