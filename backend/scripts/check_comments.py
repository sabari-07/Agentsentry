"""Confirm AgentSentry posted verification comments back onto the PRs."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import io  # noqa: E402

import httpx  # noqa: E402

from config import get_settings  # noqa: E402

# Windows consoles default to cp1252; force UTF-8 so emoji in comments print.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API = "https://api.github.com"


def main() -> None:
    s = get_settings()
    h = {
        "Authorization": f"Bearer {s.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=20, headers=h) as c:
        prs = c.get(f"{API}/repos/{s.github_repo}/pulls", params={"state": "all"}).json()
        for pr in prs[:5]:
            n = pr["number"]
            comments = c.get(f"{API}/repos/{s.github_repo}/issues/{n}/comments").json()
            print(f"\nPR #{n} ({pr['state']}): {len(comments)} comment(s)")
            for cm in comments:
                body = cm.get("body", "")
                first = body.splitlines()[0] if body else ""
                verified = "RESOLVED_VERIFIED" in body
                print(f"  - {first[:70]}")
                print(f"    contains RESOLVED_VERIFIED: {verified}")
                print(f"    url: {cm['html_url']}")


if __name__ == "__main__":
    main()
