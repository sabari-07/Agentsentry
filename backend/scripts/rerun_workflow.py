"""Re-run a failed workflow run (used to retest OIDC without a new merge)."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402

run_id = sys.argv[1]
settings = get_settings()
headers = {
    "Authorization": f"Bearer {settings.github_token}",
    "Accept": "application/vnd.github+json",
}

with httpx.Client(timeout=30, headers=headers) as client:
    resp = client.post(
        f"https://api.github.com/repos/{settings.github_repo}/actions/runs/{run_id}/rerun"
    )
    print(f"rerun requested: HTTP {resp.status_code}")
    if resp.status_code >= 300:
        print(resp.text[:400])
