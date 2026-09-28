"""Test the fixed CloudWatchService.get_metric_value against live data."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.cloudwatch_service import CloudWatchService  # noqa: E402
from config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")

s = get_settings()
# Force live mode regardless of .env for this check.
object.__setattr__(s, "use_mock_data", False)
cw = CloudWatchService(s)

print("dimensions used:", cw.build_dimensions("ThrottledRequests", "agentsentry-monitored"))
for window in (5, 15, 30):
    v = cw.get_metric_value("ThrottledRequests", "agentsentry-monitored", window)
    verdict = "HEALTHY (would verify)" if v < 1.0 else "BREACHING (would FAIL)"
    print(f"window {window:>2} min -> observed {v:g}  => {verdict}")
