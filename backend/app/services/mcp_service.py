"""Runtime client for the **AWS MCP Server** (Agent Toolkit for AWS).

The Agent Toolkit exposes a managed MCP endpoint over HTTPS
(``https://aws-mcp.<region>.api.aws/mcp``). Most MCP clients speak stdio and use
the ``mcp-proxy-for-aws`` helper, but the endpoint is a normal SigV4-signed
JSON-RPC service, so this service calls it directly from Lambda.

We use it to ground remediation in **real AWS documentation** at runtime rather
than relying on hardcoded guidance. Per AWS docs, the MCP server forwards calls
using the caller's credentials and needs no additional IAM permissions;
documentation search requires no AWS service permissions at all.
"""
from __future__ import annotations

import json
import logging

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from config import Settings

logger = logging.getLogger("agentsentry.mcp")

PROTOCOL_VERSION = "2025-06-18"


class McpDocsService:
    """Queries AWS documentation through the AWS MCP Server."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._region = settings.region
        self._endpoint = f"https://aws-mcp.{self._region}.api.aws/mcp"
        # SigV4 service name is derived from the hostname (e.g. "aws-mcp").
        self._service = "aws-mcp"
        self._session_id: str | None = None

    # ------------------------------------------------------------------ #
    # Low-level signed transport
    # ------------------------------------------------------------------ #
    def _credentials(self):
        import boto3

        session = boto3.Session(
            aws_access_key_id=self._settings.aws_access_key_id,
            aws_secret_access_key=self._settings.aws_secret_access_key,
            aws_session_token=self._settings.aws_session_token,
            region_name=self._region,
        )
        creds = session.get_credentials()
        return creds.get_frozen_credentials() if creds else None

    def _post(self, creds, payload: dict, client: httpx.Client) -> httpx.Response:
        body = json.dumps(payload)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        req = AWSRequest(method="POST", url=self._endpoint, data=body, headers=headers)
        SigV4Auth(creds, self._service, self._region).add_auth(req)
        return client.post(self._endpoint, content=body, headers=dict(req.headers))

    @staticmethod
    def _parse(resp: httpx.Response) -> dict:
        """The endpoint may answer as JSON or as a Server-Sent Events stream."""
        if "text/event-stream" in resp.headers.get("content-type", ""):
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            return {}
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def search_documentation(self, search_phrase: str, limit: int = 3) -> list[dict]:
        """Return AWS documentation results: ``[{title, url, excerpt}, ...]``.

        Never raises — on any failure it logs and returns an empty list so the
        remediation pipeline degrades gracefully.
        """
        creds = self._credentials()
        if creds is None:
            logger.warning("No AWS credentials available for MCP docs lookup.")
            return []

        try:
            with httpx.Client(timeout=25) as client:
                init = self._post(creds, {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "agentsentry-ai", "version": "1.0.0"},
                    },
                }, client)
                if init.status_code != 200:
                    logger.warning("MCP initialize failed: %s %s", init.status_code, init.text[:200])
                    return []
                self._session_id = init.headers.get("mcp-session-id")

                # Spec requires the initialized notification before tool calls.
                self._post(creds, {"jsonrpc": "2.0", "method": "notifications/initialized"}, client)

                call = self._post(creds, {
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "aws___search_documentation",
                        "arguments": {"search_phrase": search_phrase, "limit": limit},
                    },
                }, client)

            data = self._parse(call)
            if "error" in data:
                logger.warning("MCP tools/call error: %s", json.dumps(data["error"])[:200])
                return []

            return self._extract_results(data, limit)
        except Exception:  # noqa: BLE001
            logger.exception("MCP documentation lookup failed")
            return []

    @staticmethod
    def _clean(text: str) -> str:
        """Strip private-use/control glyphs the docs embed (link icons etc.)."""
        import unicodedata

        out = []
        for ch in text:
            cat = unicodedata.category(ch)
            # Co = private use, Cc/Cf = control/format. Keep normal whitespace.
            if cat in {"Co", "Cc", "Cf"} and ch not in "\n\t ":
                continue
            out.append(ch)
        return " ".join("".join(out).split())

    @classmethod
    def _extract_results(cls, data: dict, limit: int) -> list[dict]:
        """Pull {title, url, excerpt} out of the tool's content blocks."""
        blocks = data.get("result", {}).get("content", [])
        results: list[dict] = []
        for block in blocks:
            text = block.get("text") or ""
            try:
                payload = json.loads(text)
            except Exception:  # noqa: BLE001
                continue
            items = payload.get("content", {}).get("result", [])
            if not isinstance(items, list):
                continue
            for item in items:
                excerpt = cls._clean(item.get("context") or "")
                results.append({
                    "title": cls._clean(item.get("title", "AWS documentation")),
                    "url": item.get("url", ""),
                    "excerpt": (excerpt[:300] + "...") if len(excerpt) > 300 else excerpt,
                })
        logger.info("MCP docs lookup returned %d result(s)", len(results))
        return results[:limit]
