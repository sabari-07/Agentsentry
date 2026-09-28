"""Confirm what is actually deployed matches the current code.

Checks:
  1. API health / mode
  2. That the deployed verification uses the FIXED metric query (the old code
     could only ever return 0.0; the fix can return a real breaching value)
  3. Current incident states
  4. Whether the live S3 site serves the same bundle as the local build
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API = "https://6klp6vbzza.execute-api.us-east-1.amazonaws.com"
SITE = "http://agentsentry-dashboard-273354655941.s3-website-us-east-1.amazonaws.com"
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def main() -> None:
    print("=== BACKEND ===")
    h = httpx.get(f"{API}/api/health", timeout=30)
    print("health:", h.status_code, h.text)

    incidents = httpx.get(f"{API}/api/incidents", timeout=30).json()
    print(f"\nincidents: {len(incidents)}")
    for i in incidents:
        v = i.get("verification") or {}
        obs = v.get("observed_value")
        print(f"  {i['id']}: {i['status']}  observed={obs}")

    # Evidence of the fix: the OLD code queried an incomplete dimension set and
    # could only ever return 0.0. Any non-zero observed value proves the fixed
    # code is live.
    nonzero = [
        i for i in incidents
        if (i.get("verification") or {}).get("observed_value")
        not in (None, 0, 0.0)
    ]
    print("\nfix evidence (non-zero observed value recorded):",
          "YES" if nonzero else "not currently visible")

    print("\n=== FRONTEND ===")
    html = httpx.get(SITE, timeout=30, follow_redirects=True).text
    live = set(re.findall(r"assets/(index-[\w-]+\.(?:js|css))", html))
    local = {p.name for p in (DIST / "assets").glob("index-*")} if DIST.exists() else set()
    print("live bundles :", sorted(live))
    print("local bundles:", sorted(local))
    if local and live == local:
        print("=> frontend IS up to date")
    elif not local:
        print("=> no local dist to compare (run npm run build)")
    else:
        print("=> MISMATCH: local build differs from what is deployed")


if __name__ == "__main__":
    main()
