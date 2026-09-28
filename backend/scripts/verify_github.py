"""Verify the GitHub token works and can access the target repo.

Read-only checks only: who am I, and can I see the repo + its default branch.
Does not print the token.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from config import get_settings  # noqa: E402

API = "https://api.github.com"


def main() -> None:
    s = get_settings()
    if not s.github_token:
        print("ERROR: GITHUB_TOKEN not set in config/.env")
        sys.exit(1)

    h = {
        "Authorization": f"Bearer {s.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=20, headers=h) as c:
        me = c.get(f"{API}/user")
        print("auth status:", me.status_code)
        if me.status_code != 200:
            print("  body:", me.text[:200])
            sys.exit(2)
        print("  authenticated as:", me.json().get("login"))

        print(f"repo configured: {s.github_repo}")
        if "your-org" in s.github_repo:
            print("  WARNING: still the placeholder repo — set GITHUB_REPO to your real repo.")
            sys.exit(3)

        r = c.get(f"{API}/repos/{s.github_repo}")
        print("repo access:", r.status_code)
        if r.status_code != 200:
            print("  body:", r.text[:200])
            sys.exit(4)
        data = r.json()
        print("  default branch:", data.get("default_branch"))
        print("  permissions:", data.get("permissions"))

        ref = c.get(f"{API}/repos/{s.github_repo}/git/ref/heads/{s.github_base_branch}")
        print(f"base branch '{s.github_base_branch}' ref:", ref.status_code)
        if ref.status_code == 200:
            print("  head sha:", ref.json()["object"]["sha"][:10])

    print("\nGitHub is ready for real PR creation.")


if __name__ == "__main__":
    main()
