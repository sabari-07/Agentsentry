"""Parse a CloudWatch Alarm State Change event into a monitored resource.

The alarm payload EventBridge delivers already describes exactly what broke: the
namespace, the metric name, the statistic, and the metric's full dimension set.
Reading the resource from the event instead of hardcoding it means the pipeline
is resource-agnostic — point an alarm at any supported resource and the same
code path handles it, and the verification step later measures the *same* metric
the alarm measured rather than guessing at its dimensions.

Event shape (abridged):

    detail.alarmName
    detail.state.value                      -> "ALARM"
    detail.configuration.metrics[0].metricStat.metric.namespace
    detail.configuration.metrics[0].metricStat.metric.name
    detail.configuration.metrics[0].metricStat.metric.dimensions  -> {TableName: ...}
    detail.configuration.metrics[0].metricStat.stat               -> "Sum"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("agentsentry.alarm")

# namespace -> (dimension that identifies the resource, CloudFormation-style type)
_NAMESPACE_RESOURCES: dict[str, tuple[str, str]] = {
    "AWS/DynamoDB": ("TableName", "AWS::DynamoDB::Table"),
    "AWS/Lambda": ("FunctionName", "AWS::Lambda::Function"),
    "AWS/ApiGateway": ("ApiName", "AWS::ApiGateway::RestApi"),
    "AWS/ApiGatewayV2": ("ApiId", "AWS::ApiGatewayV2::Api"),
    "AWS/RDS": ("DBInstanceIdentifier", "AWS::RDS::DBInstance"),
    "AWS/SQS": ("QueueName", "AWS::SQS::Queue"),
    "AWS/ECS": ("ServiceName", "AWS::ECS::Service"),
}


@dataclass
class AlarmContext:
    """Everything the pipeline needs, read from the alarm itself."""

    alarm_name: str
    namespace: str
    metric_name: str
    statistic: str
    dimensions: dict[str, str] = field(default_factory=dict)
    resource_id: str = ""
    resource_type: str = "AWS::CloudWatch::Alarm"
    threshold: float | None = None
    state_reason: str = ""

    @property
    def is_supported(self) -> bool:
        """True when we recognise the namespace and found the resource."""
        return bool(self.resource_id) and self.namespace in _NAMESPACE_RESOURCES


def parse_alarm_event(event: dict) -> AlarmContext:
    """Build an AlarmContext from an EventBridge CloudWatch Alarm State Change.

    Never raises: unknown or malformed payloads come back with empty fields and
    ``is_supported == False`` so the caller can degrade rather than crash.
    """
    detail = event.get("detail") or {}
    config = detail.get("configuration") or {}
    state = detail.get("state") or {}

    ctx = AlarmContext(
        alarm_name=detail.get("alarmName", "unknown-alarm"),
        namespace="",
        metric_name="",
        statistic="Sum",
        state_reason=state.get("reason", ""),
    )

    metric_stat = _first_metric_stat(config)
    if metric_stat is None:
        logger.warning("Alarm %s has no readable metricStat", ctx.alarm_name)
        return ctx

    metric = metric_stat.get("metric") or {}
    ctx.namespace = metric.get("namespace", "")
    ctx.metric_name = metric.get("name", "")
    ctx.statistic = metric_stat.get("stat") or "Sum"
    # CloudWatch delivers dimensions as a plain object on this event.
    ctx.dimensions = {str(k): str(v) for k, v in (metric.get("dimensions") or {}).items()}

    mapping = _NAMESPACE_RESOURCES.get(ctx.namespace)
    if mapping:
        primary, resource_type = mapping
        ctx.resource_id = ctx.dimensions.get(primary, "")
        ctx.resource_type = resource_type
    else:
        logger.warning("Unrecognised namespace %r on alarm %s", ctx.namespace, ctx.alarm_name)

    threshold = _find_threshold(config)
    if threshold is not None:
        ctx.threshold = threshold

    logger.info(
        "Parsed alarm %s -> %s %s on %s (%s) dims=%s",
        ctx.alarm_name, ctx.namespace, ctx.metric_name,
        ctx.resource_id or "<unknown>", ctx.statistic, ctx.dimensions,
    )
    return ctx


def _first_metric_stat(config: dict) -> dict | None:
    """Return the metricStat of the metric the alarm evaluates.

    Alarms may carry several metrics (for maths expressions); prefer the one
    marked returnData, else the first that has a metricStat.
    """
    metrics = config.get("metrics") or []
    for entry in metrics:
        if entry.get("returnData") and entry.get("metricStat"):
            return entry["metricStat"]
    for entry in metrics:
        if entry.get("metricStat"):
            return entry["metricStat"]
    return None


def _find_threshold(config: dict) -> float | None:
    raw = config.get("threshold")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def resource_type_for(namespace: str) -> str:
    """Public helper so other modules don't duplicate the namespace table."""
    return _NAMESPACE_RESOURCES.get(namespace, ("", "AWS::CloudWatch::Alarm"))[1]


def supported_namespaces() -> list[str]:
    return sorted(_NAMESPACE_RESOURCES)
