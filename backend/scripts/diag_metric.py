"""Diagnose which ThrottledRequests dimension set actually has data."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402

from config import get_settings  # noqa: E402

s = get_settings()
cw = boto3.Session(
    aws_access_key_id=s.aws_access_key_id,
    aws_secret_access_key=s.aws_secret_access_key,
    region_name=s.region,
).client("cloudwatch")

TABLE = "agentsentry-monitored"
end = datetime.now(timezone.utc)
start = end - timedelta(minutes=20)

cases = {
    "TableName only": [{"Name": "TableName", "Value": TABLE}],
    "TableName + Operation=PutItem": [
        {"Name": "TableName", "Value": TABLE},
        {"Name": "Operation", "Value": "PutItem"},
    ],
}

for label, dims in cases.items():
    r = cw.get_metric_statistics(
        Namespace="AWS/DynamoDB",
        MetricName="ThrottledRequests",
        Dimensions=dims,
        StartTime=start,
        EndTime=end,
        Period=60,
        Statistics=["Maximum", "Sum"],
    )
    pts = r.get("Datapoints", [])
    total = sum(p["Sum"] for p in pts) if pts else 0
    mx = max((p["Maximum"] for p in pts), default=0)
    print(f"{label}: {len(pts)} datapoint(s), sum={total:g}, max={mx:g}")

print("\n--- what dimension combinations actually exist ---")
lm = cw.list_metrics(
    Namespace="AWS/DynamoDB",
    MetricName="ThrottledRequests",
    Dimensions=[{"Name": "TableName", "Value": TABLE}],
)
for m in lm.get("Metrics", []):
    print("  ", [(d["Name"], d["Value"]) for d in m["Dimensions"]])
