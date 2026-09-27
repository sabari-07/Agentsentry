"""Create an isolated AWS CLI named profile ('agentsentry') from config/.env.

This keeps the project pointed at account 273354655941 without touching the
user's existing default CLI profile (which is a different account). CDK and any
AWS command can then target this account with `--profile agentsentry`.

Secrets are written only to the local AWS credentials file; nothing is printed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402

PROFILE = "agentsentry"


def _set(key: str, value: str | None) -> None:
    if value is None:
        return
    subprocess.run(
        ["aws", "configure", "set", key, value, "--profile", PROFILE],
        check=True,
        shell=True,
    )


def main() -> None:
    settings = get_settings()
    if not settings.has_aws_credentials:
        print("ERROR: credentials missing in config/.env")
        sys.exit(1)

    _set("aws_access_key_id", settings.aws_access_key_id)
    _set("aws_secret_access_key", settings.aws_secret_access_key)
    if settings.aws_session_token:
        _set("aws_session_token", settings.aws_session_token)
    _set("region", settings.region)

    print(f"Profile '{PROFILE}' configured for region {settings.region}.")
    print("Use it with:  cdk deploy --profile agentsentry")


if __name__ == "__main__":
    main()
