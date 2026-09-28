"""Scheduled cleanup: delete the stored LLM credentials once judging is over.

The reasoning layer needs inference credentials only while the project is being
evaluated. Leaving them in the account indefinitely is unnecessary exposure, so
this handler removes them on a fixed date and the pipeline falls back to its
deterministic diagnosis.

Runs daily and compares the date rather than relying on a single one-off
schedule, so it survives redeploys and cannot be silently consumed early. It is
idempotent: once the credentials are gone, later runs report that and exit 0.

Scope note, deliberately stated because it is easy to get wrong: deleting the
stored copy stops *this* account from using the keys. It does **not** revoke
them. The owning account must deactivate the IAM access key itself for the
credentials to be genuinely dead.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

logger = logging.getLogger("agentsentry.expiry")
logging.getLogger().setLevel(logging.INFO)


def _parse_expiry(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        logger.error("LLM_CREDENTIAL_EXPIRY %r is not an ISO date (YYYY-MM-DD).", raw)
        return None


def _delete_parameter(name: str) -> str:
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("ssm")
    try:
        client.delete_parameter(Name=name)
        return "deleted"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ParameterNotFound":
            return "already absent"
        raise


def _delete_secret(secret_id: str) -> str:
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("secretsmanager")
    try:
        # No recovery window: the point is that the credential stops existing.
        client.delete_secret(SecretId=secret_id, ForceDeleteWithoutRecovery=True)
        return "deleted"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return "already absent"
        raise


def handler(_event: dict, _context) -> dict:
    """Delete the stored inference credentials once the expiry date has passed."""
    name = os.environ.get("LLM_SECRET_NAME", "").strip()
    expiry_raw = os.environ.get("LLM_CREDENTIAL_EXPIRY", "").strip()

    if not name or not expiry_raw:
        logger.info("No credential name or expiry configured; nothing to do.")
        return {"action": "skipped", "reason": "not configured"}

    expiry = _parse_expiry(expiry_raw)
    if expiry is None:
        # A malformed date must not cause an early deletion.
        return {"action": "skipped", "reason": "invalid expiry date"}

    today = datetime.now(timezone.utc).date()
    if today < expiry:
        remaining = (expiry - today).days
        logger.info(
            "Credentials retained: %s day(s) until expiry on %s.", remaining, expiry.isoformat()
        )
        return {
            "action": "retained",
            "expires_on": expiry.isoformat(),
            "days_remaining": remaining,
        }

    # A leading "/" means Parameter Store; anything else is Secrets Manager.
    outcome = _delete_parameter(name) if name.startswith("/") else _delete_secret(name)
    logger.info(
        "Expiry %s reached: credentials %s. Reasoning now falls back to the "
        "deterministic diagnosis. Remember to deactivate the IAM access key in "
        "the owning account — deleting this copy does not revoke it.",
        expiry.isoformat(), outcome,
    )
    return {"action": outcome, "expired_on": expiry.isoformat(), "name": name}
