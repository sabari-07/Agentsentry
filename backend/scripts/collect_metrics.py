"""Collect the real measured numbers for the submission write-up.

Read-only. Pulls incident counts/states from the live API and PR/comment counts
from GitHub so every figure quoted in the submission is verifiable.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from config import get_settings  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API = "https://6klp6vbzza.execute-api.us-east-1.amazonaws.com"
GH = "https://api.github.com"


def main() -> None:
    s = get_settings()

    incidents = httpx.get(f"{API}/api/incidents", timeout=30).json()
    print(f"incidents total: {len(incidents)}")
    states: dict[str, int] = {}
    total_audit = 0
    with_pr = 0
    for i in incidents:
        states[i["status"]] = states.get(i["status"], 0) + 1
        total_audit += len(i.get("audit_calls") or [])
        if i.get("pull_request") and i["pull_request"].get("number"):
            with_pr += 1
    print("by state:", states)
    print("incidents with a real PR:", with_pr)
    print("recorded read-only audit calls:", total_audit)

    h = {
        "Authorization": f"Bearer {s.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=25, headers=h) as c:
        prs = c.get(f"{GH}/repos/{s.github_repo}/pulls", params={"state": "all", "per_page": 100}).json()
        print(f"\nGitHub PRs total: {len(prs)}")
        agent_prs = [p for p in prs if "agentsentry-remediation" in p["head"]["ref"]]
        print(f"agent-created PRs: {len(agent_prs)}")
        comments = 0
        bodies = []
        for p in agent_prs:
            cl = c.get(f"{GH}/repos/{s.github_repo}/issues/{p['number']}/comments").json()
            comments += len(cl)
            bodies.append(len(p.get("body") or ""))
            print(f"  PR #{p['number']}: {p['state']}, body {len(p.get('body') or '')} chars, "
                  f"{len(cl)} verification comment(s)")
        print(f"\nverification comments posted: {comments}")
        if bodies:
            print(f"avg PR body length: {sum(bodies)//len(bodies)} chars")


if __name__ == "__main__":
    main()
