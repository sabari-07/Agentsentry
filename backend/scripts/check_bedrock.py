"""Check which Amazon Bedrock models are usable in this account/region.

Read-only. Filters to ACTIVE text models that support ON_DEMAND inference, then
tries a tiny Converse call against the cheapest ones to confirm real access.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

from config import get_settings  # noqa: E402

# Preference order: cheapest capable text models first.
PREFER = ["nova-micro", "nova-lite", "haiku", "nova-pro", "mistral", "llama"]


def main() -> None:
    s = get_settings()
    session = boto3.Session(
        aws_access_key_id=s.aws_access_key_id,
        aws_secret_access_key=s.aws_secret_access_key,
        aws_session_token=s.aws_session_token,
        region_name=s.region,
    )

    br = session.client("bedrock")
    models = br.list_foundation_models(byOutputModality="TEXT")["modelSummaries"]

    usable = [
        m
        for m in models
        if m.get("modelLifecycle", {}).get("status") == "ACTIVE"
        and "ON_DEMAND" in (m.get("inferenceTypesSupported") or [])
    ]
    print(f"ACTIVE + ON_DEMAND text models: {len(usable)}\n")
    for m in usable[:40]:
        print(f"  {m['modelId']}")

    # Order by our preference, then try real calls.
    def rank(mid: str) -> int:
        for i, p in enumerate(PREFER):
            if p in mid:
                return i
        return len(PREFER)

    ordered = sorted({m["modelId"] for m in usable}, key=rank)
    rt = session.client("bedrock-runtime")
    print("\nlive Converse tests (cheapest first):")
    for mid in ordered[:10]:
        for candidate in (mid, f"us.{mid}"):
            try:
                resp = rt.converse(
                    modelId=candidate,
                    messages=[{"role": "user", "content": [{"text": "Reply with OK only."}]}],
                    inferenceConfig={"maxTokens": 10, "temperature": 0},
                )
                text = resp["output"]["message"]["content"][0]["text"].strip()
                print(f"  {candidate}: WORKS -> '{text}'")
                print(f"\nUSE THIS MODEL: {candidate}")
                return
            except ClientError as e:
                code = e.response["Error"]["Code"]
                msg = e.response["Error"]["Message"][:90]
                print(f"  {candidate}: {code} - {msg}")

    print("\nNo model is invocable yet. Enable access in the Bedrock console:")
    print("  Bedrock > Model access > Modify model access > enable e.g. Amazon Nova Micro")


if __name__ == "__main__":
    main()
