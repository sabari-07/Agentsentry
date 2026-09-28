"""Serve the React dashboard over the API Gateway's HTTPS endpoint.

The dashboard is hosted on an S3 *website* endpoint, which is HTTP-only, and the
account is not yet verified for CloudFront. To give judges a genuine HTTPS URL
without waiting on that verification, the API Lambda also serves the static site:
it reads each requested object from the same S3 bucket and returns it with the
right content type, so S3 remains the single source of truth and the frontend
deploy is still a plain ``aws s3 sync``.

This router is registered **after** the ``/api`` routers, so those take
precedence; only non-API paths fall through to here. Unknown paths return
``index.html`` so the client-side router (including the ``#judges`` tour) works.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core import Container, get_container

logger = logging.getLogger("agentsentry.static")

router = APIRouter(tags=["dashboard"])

_CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "js": "application/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "json": "application/json; charset=utf-8",
    "map": "application/json; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "webmanifest": "application/manifest+json",
}

# Hashed asset filenames are immutable, so they cache hard; index.html must not,
# or a judge could be served a stale build after a deploy.
_INDEX = "index.html"
_ASSET_CACHE = "public, max-age=31536000, immutable"
_HTML_CACHE = "no-cache"


def _content_type(key: str) -> str:
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _load(container: Container, key: str) -> Response | None:
    """Return an S3 object as an HTTP response, or None if it is missing."""
    bucket = container.settings.dashboard_bucket
    if not bucket:
        return None
    try:
        import boto3

        session = boto3.Session(
            aws_access_key_id=container.settings.aws_access_key_id,
            aws_secret_access_key=container.settings.aws_secret_access_key,
            aws_session_token=container.settings.aws_session_token,
            region_name=container.settings.region,
        )
        obj = session.client("s3").get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read()
    except Exception:  # noqa: BLE001 - a missing key is normal (SPA fallback)
        return None

    cache = _HTML_CACHE if key.endswith(".html") else _ASSET_CACHE
    return Response(
        content=body,
        media_type=_content_type(key),
        headers={"Cache-Control": cache},
    )


@router.get("/")
def index(container: Container = Depends(get_container)) -> Response:
    page = _load(container, _INDEX)
    if page is not None:
        return page
    # The dashboard bucket is optional; keep the API usable without it.
    return Response(
        content="AgentSentry API is live. Dashboard asset store is not configured.",
        media_type="text/plain; charset=utf-8",
        status_code=200,
    )


@router.get("/{full_path:path}")
def spa(full_path: str, container: Container = Depends(get_container)) -> Response:
    # A real file (an /assets/... bundle) is served directly; anything else is a
    # client-side route, so fall back to index.html.
    if "." in full_path.rsplit("/", 1)[-1]:
        asset = _load(container, full_path)
        if asset is not None:
            return asset
        return Response(content="Not found", media_type="text/plain", status_code=404)

    page = _load(container, _INDEX)
    if page is not None:
        return page
    return Response(content="Not found", media_type="text/plain", status_code=404)
