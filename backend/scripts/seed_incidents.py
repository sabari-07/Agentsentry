"""Seed the live DynamoDB incident table with demo data.

Run this once after deploying the CDK stack so the live dashboard shows the same
story-driven incidents (resolved / PR-open / diagnosing) as mock mode.

Usage (from backend/, with AWS creds configured and config/.env pointing at the
deployed table, USE_MOCK_DATA=false):

    python scripts/seed_incidents.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script: make the backend package importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.mock_data import build_seed_incidents  # noqa: E402
from config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    if settings.use_mock_data:
        print("USE_MOCK_DATA is true — nothing to seed. Set it to false to seed live DynamoDB.")
        return

    from app.services import IncidentStore

    store = IncidentStore(settings)
    incidents = build_seed_incidents(settings.agent_iam_principal)
    for incident in incidents:
        store.save_incident(incident)
        print(f"seeded {incident.id} ({incident.status.value})")

    print(f"\nDone. Seeded {len(incidents)} incidents into {settings.incident_table_name}.")


if __name__ == "__main__":
    main()
