"""Print the failing step's log lines for a workflow run."""
from __future__ import annotations

import sys
import zipfile
from io import BytesIO
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402

run_id = sys.argv[1]
settings = get_settings()
headers = {
    "Authorization": f"Bearer {settings.github_token}",
    "Accept": "application/vnd.github+json",
}
base = f"https://api.github.com/repos/{settings.github_repo}"

with httpx.Client(timeout=60, headers=headers, follow_redirects=True) as client:
    resp = client.get(f"{base}/actions/runs/{run_id}/logs")
    resp.raise_for_status()
    with zipfile.ZipFile(BytesIO(resp.content)) as archive:
        for name in archive.namelist():
            if "credential" not in name.lower():
                continue
            print(f"===== {name} =====")
            text = archive.read(name).decode("utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.split("Z ", 1)[-1]
                if stripped.strip():
                    print(stripped)
