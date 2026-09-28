"""Show the files a remediation PR actually changes, and the IaC diff itself."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402

number = int(sys.argv[1]) if len(sys.argv) > 1 else 8
settings = get_settings()
headers = {
    "Authorization": f"Bearer {settings.github_token}",
    "Accept": "application/vnd.github+json",
}

with httpx.Client(timeout=30, headers=headers) as client:
    pr = client.get(
        f"https://api.github.com/repos/{settings.github_repo}/pulls/{number}"
    ).json()
    print(f"PR #{number}: {pr['title']}")
    print(f"state={pr['state']} mergeable={pr.get('mergeable')} base={pr['base']['ref']}")

    files = client.get(
        f"https://api.github.com/repos/{settings.github_repo}/pulls/{number}/files"
    ).json()
    print(f"\nchanged files ({len(files)}):")
    for f in files:
        print(f"  {f['filename']}  +{f['additions']}/-{f['deletions']}")

    for f in files:
        if f["filename"].endswith("stack.py"):
            print("\n--- infrastructure diff ---")
            print(f.get("patch", "(no patch returned)"))
