"""Verify AWS credentials from config/.env are valid and point to the expected account.

Makes a single harmless read-only call (STS GetCallerIdentity). Prints the
account it resolved to so we can confirm it matches the intended account before
deploying anything. Does not print secret values.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402

from config import get_settings  # noqa: E402

EXPECTED_ACCOUNT = "273354655941"


def main() -> None:
    settings = get_settings()

    if not settings.has_aws_credentials:
        print("ERROR: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are empty in config/.env")
        sys.exit(1)

    session = boto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        aws_session_token=settings.aws_session_token,
        region_name=settings.region,
    )
    sts = session.client("sts")
    identity = sts.get_caller_identity()

    account = identity["Account"]
    print("Credentials are VALID.")
    print(f"  Account: {account}")
    print(f"  ARN:     {identity['Arn']}")
    print(f"  Region:  {settings.region}")

    if account == EXPECTED_ACCOUNT:
        print(f"\nOK: this matches the expected account {EXPECTED_ACCOUNT}.")
    else:
        print(f"\nWARNING: expected {EXPECTED_ACCOUNT} but got {account}.")
        print("Do NOT deploy until this points at the correct account.")
        sys.exit(2)


if __name__ == "__main__":
    main()
