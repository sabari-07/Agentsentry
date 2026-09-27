"""Delete all incident records from the live DynamoDB incident table.

Use before a live demo so only genuinely self-generated incidents remain.
Usage:  python scripts/clear_incidents.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402

from config import get_settings  # noqa: E402


def main() -> None:
    s = get_settings()
    session = boto3.Session(
        aws_access_key_id=s.aws_access_key_id,
        aws_secret_access_key=s.aws_secret_access_key,
        aws_session_token=s.aws_session_token,
        region_name=s.region,
    )
    table = session.resource("dynamodb").Table(s.incident_table_name)
    scanned = table.scan(ProjectionExpression="id").get("Items", [])
    for item in scanned:
        table.delete_item(Key={"id": item["id"]})
        print("deleted", item["id"])
    print(f"Cleared {len(scanned)} incidents from {s.incident_table_name}.")


if __name__ == "__main__":
    main()
