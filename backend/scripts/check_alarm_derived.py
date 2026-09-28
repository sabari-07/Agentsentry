"""Confirm the newest incident derived its resource + metric from the alarm."""
from __future__ import annotations

import io
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API = "https://6klp6vbzza.execute-api.us-east-1.amazonaws.com"

incidents = httpx.get(f"{API}/api/incidents", timeout=30).json()
print(f"incidents: {len(incidents)}\n")

newest = incidents[0]
print(f"newest: {newest['id']}  status={newest['status']}")
print(f"  title            : {newest['title']}")
print(f"  resource_id      : {newest['resource_id']}")
print(f"  resource_type    : {newest['resource_type']}")
print(f"  alarm_name       : {newest.get('alarm_name')}")
print(f"  metric_namespace : {newest.get('metric_namespace')}")
print(f"  metric_name      : {newest['metric_name']}")
print(f"  metric_statistic : {newest.get('metric_statistic')}")
print(f"  metric_dimensions: {newest.get('metric_dimensions')}")
pr = newest.get("pull_request") or {}
if pr.get("url"):
    print(f"  PR               : {pr['url']}")

derived = bool(newest.get("metric_dimensions")) and bool(newest.get("alarm_name"))
print("\nresource + metric identity read from the alarm:", "YES" if derived else "NO")
