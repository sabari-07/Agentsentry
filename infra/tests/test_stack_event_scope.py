"""Infrastructure tests for the alarm routing scope.

The EventBridge rule must NOT be pinned to a single alarm name. The incident
handler identifies the affected resource from the alarm payload, so scoping the
rule to one alarm would silently reduce the product to watching one resource —
which is exactly the limitation this design removes.
"""
from __future__ import annotations

import os
from functools import lru_cache

import aws_cdk as cdk
from aws_cdk.assertions import Template

from agentsentry.stack import AgentSentryStack


@lru_cache(maxsize=1)
def _template() -> Template:
    """Synthesise once and reuse; synth is the expensive part of these tests."""
    # Skip the Lambda dependency bundling: these assertions only inspect the
    # generated CloudFormation, not the packaged code.
    os.environ["AGENTSENTRY_SKIP_BUNDLE"] = "1"
    app = cdk.App()
    stack = AgentSentryStack(
        app, "TestStack", env=cdk.Environment(account="123456789012", region="us-east-1")
    )
    return Template.from_stack(stack)


def _alarm_rule(template: Template) -> dict:
    rules = template.find_resources("AWS::Events::Rule")
    assert rules, "expected an EventBridge rule routing alarms to the handler"
    # There is a single rule in this stack; return its properties.
    return next(iter(rules.values()))["Properties"]


def test_rule_listens_to_cloudwatch_alarm_state_changes():
    pattern = _alarm_rule(_template())["EventPattern"]
    assert pattern["source"] == ["aws.cloudwatch"]
    assert pattern["detail-type"] == ["CloudWatch Alarm State Change"]


def test_rule_is_not_scoped_to_a_single_alarm():
    """Regression: an alarmName filter would limit us to one resource."""
    detail = _alarm_rule(_template())["EventPattern"]["detail"]
    assert "alarmName" not in detail, (
        "the rule must accept alarms for any resource; the handler derives the "
        "resource from the payload"
    )


def test_rule_only_reacts_to_the_alarm_state():
    """OK and INSUFFICIENT_DATA transitions must not create incidents."""
    detail = _alarm_rule(_template())["EventPattern"]["detail"]
    assert detail["state"]["value"] == ["ALARM"]


def test_rule_targets_the_incident_handler():
    template = _template()
    rule = _alarm_rule(template)
    targets = rule.get("Targets") or []
    assert len(targets) == 1, "the rule should invoke exactly one handler"


def test_incident_handler_can_read_metrics_and_describe_tables():
    """Identifying an arbitrary resource requires read-only access."""
    template = _template()
    policies = template.find_resources("AWS::IAM::Policy")
    actions: set[str] = set()
    for policy in policies.values():
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            raw = statement.get("Action")
            if isinstance(raw, str):
                actions.add(raw)
            elif isinstance(raw, list):
                actions.update(a for a in raw if isinstance(a, str))

    assert "cloudwatch:GetMetricStatistics" in actions
    assert "dynamodb:DescribeTable" in actions
