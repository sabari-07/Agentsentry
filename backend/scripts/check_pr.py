"""Inspect the most recent remediation PR and save its body for review."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from config import get_settings  # noqa: E402

API = "https://api.github.com"

SECTIONS = [
    "Incident summary",
    "What went wrong",
    "Evidence gathered",
    "Why this matters",
    "The fix in this pull request",
    "Alternatives considered",
    "Cost impact",
    "How this will be verified",
    "Rollback plan",
    "Read-only audit trail",
]


def main() -> None:
    s = get_settings()
    h = {
        "Authorization": f"Bearer {s.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=20, headers=h) as c:
        prs = c.get(f"{API}/repos/{s.github_repo}/pulls", params={"state": "open"}).json()
        print(f"open PRs: {len(prs)}")
        if not prs:
            return
        pr = prs[0]
        print(f"\n#{pr['number']} {pr['title']}")
        print(f"  url:    {pr['html_url']}")
        print(f"  branch: {pr['head']['ref']} -> {pr['base']['ref']}")
        files = c.get(f"{API}/repos/{s.github_repo}/pulls/{pr['number']}/files").json()
        print(f"  files:  {[f['filename'] for f in files]}")
        body = pr.get("body") or ""
        print(f"  body length: {len(body)} chars")
        print("  sections present:")
        for sec in SECTIONS:
            print(f"    {sec}: {sec in body}")
        out = Path("latest_pr_body.md")
        out.write_text(body, encoding="utf-8")
        print(f"\n  saved body to {out}")


if __name__ == "__main__":
    main()
