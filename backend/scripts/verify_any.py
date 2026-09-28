"""Run the verification loop on any incident, whatever its current state.

Used to demonstrate that verification is a real measurement: run it while the
metric is still breaching and the incident is marked FAILED; run it again after
the metric recovers and it becomes RESOLVED_VERIFIED.
"""
from __future__ import annotations

import io
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API = "https://6klp6vbzza.execute-api.us-east-1.amazonaws.com"

target = sys.argv[1] if len(sys.argv) > 1 else None

incidents = httpx.get(f"{API}/api/incidents", timeout=30).json()
if target:
    incidents = [i for i in incidents if i["id"] == target]
else:
    # Newest first; verify only the most recent one.
    incidents = incidents[:1]

for i in incidents:
    r = httpx.post(f"{API}/api/verification/{i['id']}", timeout=60)
    print(f"{i['id']}  (was {i['status']})  -> HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        v = d.get("verification") or {}
        print(f"  new status : {d['status']}")
        print(f"  metric     : {v.get('metric_name')}")
        print(f"  observed   : {v.get('observed_value')}  (threshold {v.get('threshold')})")
        print(f"  summary    : {v.get('summary')}")
        pr = d.get("pull_request") or {}
        if pr.get("url"):
            print(f"  PR         : {pr['url']}")
