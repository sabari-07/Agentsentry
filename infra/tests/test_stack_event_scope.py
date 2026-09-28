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
    """Return the alarm-routing rule specifically.

    The stack contains more than one EventBridge rule (the scheduled credential
    expiry is the other), so select by name rather than taking the first match.
    """
    rules = template.find_resources("AWS::Events::Rule")
    assert rules, "expected an EventBridge rule routing alarms to the handler"
    matches = [
        resource["Properties"]
        for resource in rules.values()
        if resource["Properties"].get("Name") == "agentsentry-alarm-to-incident"
    ]
    assert len(matches) == 1, (
        "expected exactly one alarm-to-incident rule, found "
        f"{len(matches)} among {len(rules)} rule(s)"
    )
    return matches[0]


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


# --------------------------------------------------------------------------- #
# Scheduled credential expiry
# --------------------------------------------------------------------------- #
def _expiry_rule(template: Template) -> dict:
    rules = template.find_resources("AWS::Events::Rule")
    matches = [
        resource["Properties"]
        for resource in rules.values()
        if resource["Properties"].get("Name") == "agentsentry-credential-expiry"
    ]
    assert len(matches) == 1, "expected exactly one credential-expiry rule"
    return matches[0]


def test_credential_expiry_runs_on_a_schedule_not_an_event_pattern():
    rule = _expiry_rule(_template())
    assert "ScheduleExpression" in rule
    # Daily, so the handler's own date comparison decides when to act.
    assert rule["ScheduleExpression"].startswith("cron(")
    assert "EventPattern" not in rule


def test_credential_expiry_lambda_can_only_delete_the_llm_credential():
    """The delete grant must not extend to other parameters or secrets."""
    template = _template()
    statements = [
        statement
        for policy in template.find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    deletes = [
        s for s in statements
        if "ssm:DeleteParameter" in str(s.get("Action")) 
        or "secretsmanager:DeleteSecret" in str(s.get("Action"))
    ]
    assert deletes, "expected a delete grant for the LLM credential"
    for statement in deletes:
        resources = str(statement["Resource"])
        assert "agentsentry/llm" in resources, f"delete grant is too broad: {resources}"
        assert resources.count("*") <= 1, f"wildcard delete grant: {resources}"


def test_expiry_date_is_after_the_winner_announcement():
    """Winners are announced the week of 19 Oct 2026; expiry must follow it."""
    from datetime import date

    from agentsentry.stack import LLM_CREDENTIAL_EXPIRY

    expiry = date.fromisoformat(LLM_CREDENTIAL_EXPIRY)
    assert expiry > date(2026, 10, 24), "expiry must leave room for judging to finish"
