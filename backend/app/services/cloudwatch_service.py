"""CloudWatch access for the verification loop.

Reads a single metric over a short window to confirm an incident's metric has
returned to healthy after a remediation deploy. All calls are read-only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config import Settings

logger = logging.getLogger("agentsentry.cloudwatch")

# Maps a metric name to the CloudWatch namespace/dimension needed to query it.
_METRIC_SPECS: dict[str, dict[str, str]] = {
    "ThrottledRequests": {"namespace": "AWS/DynamoDB", "dimension": "TableName"},
    "Duration": {"namespace": "AWS/Lambda", "dimension": "FunctionName"},
    "5XXError": {"namespace": "AWS/ApiGateway", "dimension": "ApiName"},
}


class CloudWatchService:
    """Fetch metric statistics for verification."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None if settings.use_mock_data else self._init_client()

    def _init_client(self):
        import boto3

        session = boto3.Session(
            aws_access_key_id=self._settings.aws_access_key_id,
            aws_secret_access_key=self._settings.aws_secret_access_key,
            aws_session_token=self._settings.aws_session_token,
            region_name=self._settings.region,
        )
        return session.client("cloudwatch")

    def get_metric_value(self, metric_name: str, resource_id: str, window_minutes: int) -> float:
        """Return the max observed value of ``metric_name`` over the window.

        In mock mode this returns 0.0 (healthy) so the verification loop can be
        demoed without live infrastructure.
        """
        if self._settings.use_mock_data:
            logger.info("[mock] metric %s for %s -> 0.0", metric_name, resource_id)
            return 0.0

        spec = _METRIC_SPECS.get(metric_name)
        if spec is None:
            raise ValueError(f"Unsupported metric for verification: {metric_name}")

        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=window_minutes)
        response = self._client.get_metric_statistics(
            Namespace=spec["namespace"],
            MetricName=metric_name,
            Dimensions=[{"Name": spec["dimension"], "Value": resource_id}],
            StartTime=start,
            EndTime=end,
            Period=60,
            Statistics=["Maximum"],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return 0.0
        return max(dp["Maximum"] for dp in datapoints)
