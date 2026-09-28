"""Test the McpDocsService against the live AWS MCP Server (Agent Toolkit)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging  # noqa: E402

from app.services.mcp_service import McpDocsService  # noqa: E402
from config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO)

svc = McpDocsService(get_settings())
results = svc.search_documentation(
    "DynamoDB ThrottledRequests provisioned capacity switch to on-demand PAY_PER_REQUEST",
    limit=3,
)
print(f"\nresults: {len(results)}")
for r in results:
    print(f"\n- {r['title']}")
    print(f"  {r['url']}")
    print(f"  {r['excerpt'][:180]}")
