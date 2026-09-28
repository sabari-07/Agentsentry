"""Audit deployed resources for anything that could incur charges.

Read-only. Lists the resources in the stack and flags known billing risks.
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

    print("=== DynamoDB tables ===")
    ddb = session.client("dynamodb")
    for name in ddb.list_tables()["TableNames"]:
        t = ddb.describe_table(TableName=name)["Table"]
        mode = (t.get("BillingModeSummary") or {}).get("BillingMode", "PROVISIONED")
        pt = t.get("ProvisionedThroughput") or {}
        print(f"  {name}: mode={mode} RCU={pt.get('ReadCapacityUnits')} "
              f"WCU={pt.get('WriteCapacityUnits')} items={t.get('ItemCount')} "
              f"bytes={t.get('TableSizeBytes')}")

    print("\n=== Lambda functions ===")
    lam = session.client("lambda")
    for f in lam.list_functions()["Functions"]:
        if "agentsentry" in f["FunctionName"]:
            print(f"  {f['FunctionName']}: mem={f['MemorySize']}MB timeout={f['Timeout']}s")

    print("\n=== CloudWatch alarms ===")
    cw = session.client("cloudwatch")
    alarms = cw.describe_alarms()["MetricAlarms"]
    print(f"  total alarms: {len(alarms)} (free tier: 10 alarms)")
    for a in alarms:
        print(f"    {a['AlarmName']}: state={a['StateValue']}")

    print("\n=== CloudTrail trails (should be NONE for $0) ===")
    ct = session.client("cloudtrail")
    trails = ct.describe_trails()["trailList"]
    if not trails:
        print("  no trails — using free Event history only. GOOD")
    for t in trails:
        print(f"  WARNING trail: {t['Name']} s3={t.get('S3BucketName')}")

    print("\n=== S3 buckets ===")
    s3 = session.client("s3")
    for b in s3.list_buckets()["Buckets"]:
        print(f"  {b['Name']}")

    print("\n=== API Gateway (HTTP APIs) ===")
    api = session.client("apigatewayv2")
    for a in api.get_apis()["Items"]:
        print(f"  {a['Name']} ({a['ProtocolType']})")


if __name__ == "__main__":
    main()
