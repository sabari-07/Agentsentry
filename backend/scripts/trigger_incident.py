"""Generate a REAL incident by driving the monitored DynamoDB table into throttling.

The monitored table is provisioned at 1 WCU, so a burst of concurrent writes
exceeds capacity and produces real ThrottledRequests. That trips the CloudWatch
alarm -> EventBridge -> incident Lambda, which inspects the table for real and
records a genuine incident. Nothing here is seeded.

Usage (from backend/, AWS creds in config/.env or profile):
    python scripts/trigger_incident.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402

from config import get_settings  # noqa: E402

TABLE = "agentsentry-monitored"
TOTAL_WRITES = 800
WORKERS = 40


def main() -> None:
    settings = get_settings()
    session = boto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        aws_session_token=settings.aws_session_token,
        region_name=settings.region,
    )
    # Disable SDK auto-retries so throttling surfaces as real ThrottledRequests.
    ddb = session.client("dynamodb", config=Config(retries={"max_attempts": 0}))

    throttled = 0
    ok = 0

    def put(i: int) -> str:
        try:
            ddb.put_item(
                TableName=TABLE,
                Item={"pk": {"S": f"load-{i}-{time.time_ns()}"}, "payload": {"S": "x" * 2000}},
            )
            return "ok"
        except ddb.exceptions.ProvisionedThroughputExceededException:
            return "throttled"
        except Exception as e:  # noqa: BLE001
            return f"err:{type(e).__name__}"

    print(f"Hammering {TABLE} with {TOTAL_WRITES} writes across {WORKERS} workers…")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for result in pool.map(put, range(TOTAL_WRITES)):
            if result == "throttled":
                throttled += 1
            elif result == "ok":
                ok += 1

    print(f"Done. ok={ok}, throttled={throttled}")
    if throttled == 0:
        print("No throttling observed — re-run, or lower table capacity / raise TOTAL_WRITES.")
    else:
        print("Real ThrottledRequests generated. The CloudWatch alarm should fire within ~1-2 min,")
        print("then EventBridge invokes the incident Lambda and a real incident appears on the dashboard.")


if __name__ == "__main__":
    main()
