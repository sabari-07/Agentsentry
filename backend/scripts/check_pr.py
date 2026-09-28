"""Inspect the most recent remediation PR to confirm its contents."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from config import get_settings  # noqa: E402

API = "https://api.github.com"


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
        for pr in prs[:1]:
            print(f"\n#{pr['number']} {pr['title']}")
            print(f"  url:    {pr['html_url']}")
            print(f"  branch: {pr['head']['ref']} -> {pr['base']['ref']}")
            print(f"  state:  {pr['state']}, mergeable_state: {pr.get('mergeable_state')}")
            files = c.get(f"{API}/repos/{s.github_repo}/pulls/{pr['number']}/files").json()
            print(f"  files changed: {[f['filename'] for f in files]}")
            body = pr.get("body") or ""
            print("\n  --- PR body checks ---")
            for token in ["Diagnosis", "cdk diff", "Cost delta", "Rollback plan", "read-only"]:
                print(f"   contains '{token}':", token.lower() in body.lower())


if __name__ == "__main__":
    main()
