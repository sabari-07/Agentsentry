"""Merge a remediation PR, to exercise the deploy-then-verify pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402

number = int(sys.argv[1])
settings = get_settings()
headers = {
    "Authorization": f"Bearer {settings.github_token}",
    "Accept": "application/vnd.github+json",
}

with httpx.Client(timeout=30, headers=headers) as client:
    resp = client.put(
        f"https://api.github.com/repos/{settings.github_repo}/pulls/{number}/merge",
        json={
            "merge_method": "merge",
            "commit_title": f"Merge remediation PR #{number}",
        },
    )
    print(f"HTTP {resp.status_code}")
    print(resp.json())
