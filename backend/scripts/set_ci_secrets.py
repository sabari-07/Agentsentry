"""Create the GitHub Actions secrets the deploy workflow needs.

Values are sealed with the repository's public key (libsodium sealed box) before
they leave this machine, which is what the GitHub secrets API requires. Secret
values are never printed; only names and status codes are.

GitHub reserves the ``GITHUB_`` name prefix, so the personal access token is
stored as ``AGENTSENTRY_GH_TOKEN`` and mapped back to ``GITHUB_TOKEN`` inside the
workflow. The repository slug and base branch are not secrets and are derived
from the workflow context instead.
"""
from __future__ import annotations

import sys
from base64 import b64encode
from pathlib import Path

import httpx
from nacl import encoding, public

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402

ROLE_ARN = "arn:aws:iam::273354655941:role/agentsentry-github-deploy"
API = "https://api.github.com"


def seal(public_key_b64: str, secret_value: str) -> str:
    """Encrypt a value for the repository, per the GitHub secrets API."""
    key = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    return b64encode(public.SealedBox(key).encrypt(secret_value.encode())).decode()


def main() -> int:
    settings = get_settings()
    token = settings.github_token
    repo = settings.github_repo
    if not token or not repo:
        print("GITHUB_TOKEN/GITHUB_REPO missing from backend/config/.env")
        return 1

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    with httpx.Client(timeout=30, headers=headers) as client:
        key_resp = client.get(f"{API}/repos/{repo}/actions/secrets/public-key")
        key_resp.raise_for_status()
        key_data = key_resp.json()

        # Confirm the reserved-prefix rule rather than assuming it.
        probe = client.put(
            f"{API}/repos/{repo}/actions/secrets/GITHUB_REPO",
            json={
                "encrypted_value": seal(key_data["key"], repo),
                "key_id": key_data["key_id"],
            },
        )
        print(f"reserved-prefix probe (GITHUB_REPO): HTTP {probe.status_code}")
        if probe.status_code < 300:
            print("  unexpected: GitHub accepted a GITHUB_-prefixed secret")
        else:
            detail = probe.json().get("message", "")
            print(f"  rejected as expected: {detail}")

        wanted = {
            "AWS_DEPLOY_ROLE_ARN": ROLE_ARN,
            "AGENTSENTRY_GH_TOKEN": token,
        }
        for name, value in wanted.items():
            resp = client.put(
                f"{API}/repos/{repo}/actions/secrets/{name}",
                json={
                    "encrypted_value": seal(key_data["key"], value),
                    "key_id": key_data["key_id"],
                },
            )
            resp.raise_for_status()
            print(f"set secret {name}: HTTP {resp.status_code}")

        listed = client.get(f"{API}/repos/{repo}/actions/secrets")
        listed.raise_for_status()
        names = sorted(s["name"] for s in listed.json()["secrets"])
        print(f"secrets now present: {names}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
