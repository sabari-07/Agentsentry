"""Report the latest workflow runs and each job's conclusion."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402

settings = get_settings()
headers = {
    "Authorization": f"Bearer {settings.github_token}",
    "Accept": "application/vnd.github+json",
}
base = f"https://api.github.com/repos/{settings.github_repo}"

with httpx.Client(timeout=30, headers=headers) as client:
    runs = client.get(f"{base}/actions/runs", params={"per_page": 3}).json()
    for run in runs["workflow_runs"]:
        print(
            f"run #{run['run_number']} event={run['event']} "
            f"status={run['status']} conclusion={run['conclusion']}"
        )
        print(f"  {run['html_url']}")
        jobs = client.get(f"{base}/actions/runs/{run['id']}/jobs").json()
        for job in jobs["jobs"]:
            print(f"    job={job['name']:10} status={job['status']:12} conclusion={job['conclusion']}")
            for step in job.get("steps", []):
                if step["conclusion"] not in (None, "skipped"):
                    print(f"       - {step['name']}: {step['conclusion']}")
