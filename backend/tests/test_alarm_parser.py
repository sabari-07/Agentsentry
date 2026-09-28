"""Tests for reading the affected resource out of the alarm payload.

Previously the incident handler hardcoded the monitored resource, so the pipeline
only really worked for one table. The resource, metric, statistic and dimension
set are all present in the CloudWatch Alarm State Change event, so reading them
from the event makes the pipeline resource-agnostic — and lets verification
re-read exactly the metric that fired instead of reconstructing its dimensions.
"""
from __future__ import annotations

from app.services.alarm_parser import (
    parse_alarm_event,
    resource_type_for,
    supported_namespaces,
)


def _event(namespace="AWS/DynamoDB", name="ThrottledRequests",
           dimensions=None, stat="Sum", alarm="my-alarm",
           return_data=True, threshold=1) -> dict:
    """A realistic CloudWatch Alarm State Change payload."""
    if dimensions is None:
        dimensions = {"TableName": "orders", "Operation": "PutItem"}
    return {
        "detail-type": "CloudWatch Alarm State Change",
        "source": "aws.cloudwatch",
        "detail": {
            "alarmName": alarm,
            "state": {"value": "ALARM", "reason": "Threshold Crossed"},
            "configuration": {
                "threshold": threshold,
                "metrics": [
                    {
                        "id": "m1",
                        "returnData": return_data,
                        "metricStat": {
                            "metric": {
                                "namespace": namespace,
                                "name": name,
                                "dimensions": dimensions,
                            },
                            "period": 60,
                            "stat": stat,
                        },
                    }
                ],
            },
        },
    }


# --------------------------------------------------------------------------- #
# The resource comes from the event, not from a constant
# --------------------------------------------------------------------------- #
def test_reads_the_table_name_from_the_alarm():
    ctx = parse_alarm_event(_event(dimensions={"TableName": "orders", "Operation": "PutItem"}))

    assert ctx.resource_id == "orders", "resource must come from the alarm, not a hardcoded name"
    assert ctx.resource_type == "AWS::DynamoDB::Table"
    assert ctx.namespace == "AWS/DynamoDB"
    assert ctx.metric_name == "ThrottledRequests"
    assert ctx.is_supported


def test_a_different_table_produces_a_different_resource():
    a = parse_alarm_event(_event(dimensions={"TableName": "table-a"}))
    b = parse_alarm_event(_event(dimensions={"TableName": "table-b"}))
    assert (a.resource_id, b.resource_id) == ("table-a", "table-b")


def test_captures_the_full_dimension_set_for_verification():
    """Verification must be able to re-read the identical metric."""
    ctx = parse_alarm_event(_event(dimensions={"TableName": "orders", "Operation": "PutItem"}))
    assert ctx.dimensions == {"TableName": "orders", "Operation": "PutItem"}


def test_captures_the_statistic_the_alarm_used():
    assert parse_alarm_event(_event(stat="Sum")).statistic == "Sum"
    assert parse_alarm_event(_event(stat="Maximum")).statistic == "Maximum"


def test_captures_alarm_name_threshold_and_reason():
    ctx = parse_alarm_event(_event(alarm="prod-throttling", threshold=5))
    assert ctx.alarm_name == "prod-throttling"
    assert ctx.threshold == 5.0
    assert "Threshold" in ctx.state_reason


# --------------------------------------------------------------------------- #
# Other AWS services route through the same code path
# --------------------------------------------------------------------------- #
def test_supports_lambda_functions():
    ctx = parse_alarm_event(
        _event(namespace="AWS/Lambda", name="Duration",
               dimensions={"FunctionName": "checkout"}, stat="Maximum")
    )
    assert ctx.resource_id == "checkout"
    assert ctx.resource_type == "AWS::Lambda::Function"
    assert ctx.is_supported


def test_supports_api_gateway():
    ctx = parse_alarm_event(
        _event(namespace="AWS/ApiGateway", name="5XXError", dimensions={"ApiName": "public-api"})
    )
    assert ctx.resource_id == "public-api"
    assert ctx.resource_type == "AWS::ApiGateway::RestApi"


def test_supports_sqs_and_rds():
    sqs = parse_alarm_event(
        _event(namespace="AWS/SQS", name="ApproximateAgeOfOldestMessage",
               dimensions={"QueueName": "jobs"})
    )
    rds = parse_alarm_event(
        _event(namespace="AWS/RDS", name="CPUUtilization",
               dimensions={"DBInstanceIdentifier": "primary"})
    )
    assert sqs.resource_id == "jobs"
    assert rds.resource_id == "primary"


def test_namespace_table_is_exposed_for_documentation():
    assert "AWS/DynamoDB" in supported_namespaces()
    assert resource_type_for("AWS/Lambda") == "AWS::Lambda::Function"


# --------------------------------------------------------------------------- #
# Malformed input degrades instead of crashing
# --------------------------------------------------------------------------- #
def test_unknown_namespace_is_reported_as_unsupported_not_an_error():
    ctx = parse_alarm_event(_event(namespace="AWS/Neptune", dimensions={"Cluster": "x"}))
    assert ctx.is_supported is False
    assert ctx.namespace == "AWS/Neptune"


def test_event_without_metrics_does_not_raise():
    ctx = parse_alarm_event({"detail": {"alarmName": "bare"}})
    assert ctx.alarm_name == "bare"
    assert ctx.is_supported is False
    assert ctx.resource_id == ""


def test_completely_empty_event_does_not_raise():
    ctx = parse_alarm_event({})
    assert ctx.is_supported is False


def test_prefers_the_metric_marked_return_data():
    """Maths-expression alarms carry several metrics; pick the evaluated one."""
    event = _event()
    event["detail"]["configuration"]["metrics"].insert(0, {
        "id": "e1",
        "returnData": False,
        "metricStat": {
            "metric": {"namespace": "AWS/DynamoDB", "name": "Ignored",
                       "dimensions": {"TableName": "wrong-table"}},
            "period": 60, "stat": "Sum",
        },
    })
    ctx = parse_alarm_event(event)
    assert ctx.resource_id == "orders"
    assert ctx.metric_name == "ThrottledRequests"


def test_falls_back_to_first_metric_when_none_marked_return_data():
    ctx = parse_alarm_event(_event(return_data=False))
    assert ctx.resource_id == "orders"


def test_missing_primary_dimension_is_unsupported():
    ctx = parse_alarm_event(_event(dimensions={"Operation": "PutItem"}))
    assert ctx.resource_id == ""
    assert ctx.is_supported is False
