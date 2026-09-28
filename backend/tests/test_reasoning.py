"""Tests for the LLM reasoning layer and, more importantly, its guardrails.

The model is allowed to be wrong. It is not allowed to act outside the fixed
action set, retarget a different resource, or take down the pipeline when it
fails. These tests pin that boundary.
"""
from __future__ import annotations

import json
import sys

from app.services.reasoning_service import (
    ACTION_NO_SAFE_FIX,
    ACTION_SET_ON_DEMAND,
    ReasoningService,
)
from config import Settings


def _settings(**overrides) -> Settings:
    base = dict(use_mock_data=True, aws_region="us-east-1")
    base.update(overrides)
    return Settings(**base)


def _reply(**overrides) -> str:
    payload = {
        "root_cause": "Provisioned write capacity of 1 WCU is below the offered write rate.",
        "action": ACTION_SET_ON_DEMAND,
        "target_resource": "agentsentry-monitored",
        "confidence": "high",
        "reasoning": "105 PutItem requests were refused while the table allowed ~1 write/sec.",
        "impact": "- Writes were rejected and unretried writes were lost.",
        "rejected_alternatives": ["Raise WCU — still a fixed ceiling"],
    }
    payload.update(overrides)
    return json.dumps(payload)


# --------------------------------------------------------------------------- #
# Decision parsing
# --------------------------------------------------------------------------- #
def test_accepts_a_well_formed_decision():
    decision = ReasoningService._validate(
        _reply(), expected_resource="agentsentry-monitored"
    )
    assert decision is not None
    assert decision.action == ACTION_SET_ON_DEMAND
    assert decision.proposes_change is True


def test_tolerates_a_fenced_json_reply():
    fenced = f"```json\n{_reply()}\n```"
    assert ReasoningService._validate(fenced, expected_resource="agentsentry-monitored")


def test_tolerates_prose_around_the_json():
    noisy = f"Here is my analysis.\n\n{_reply()}\n\nHope that helps."
    assert ReasoningService._validate(noisy, expected_resource="agentsentry-monitored")


def test_rejects_unparseable_reply():
    assert ReasoningService._validate("I could not determine the cause.",
                                      expected_resource="agentsentry-monitored") is None


def test_rejects_reply_missing_required_fields():
    incomplete = json.dumps({"root_cause": "x", "action": ACTION_SET_ON_DEMAND})
    assert ReasoningService._validate(incomplete,
                                      expected_resource="agentsentry-monitored") is None


def test_rejects_action_outside_the_allowlist():
    rogue = _reply(action="DELETE_TABLE")
    assert ReasoningService._validate(rogue, expected_resource="agentsentry-monitored") is None


# --------------------------------------------------------------------------- #
# The guardrail that matters most
# --------------------------------------------------------------------------- #
def test_rejects_decision_targeting_a_different_resource():
    """A confident model must not be able to redirect the fix elsewhere."""
    hijack = _reply(target_resource="production-payments-table")
    assert ReasoningService._validate(hijack,
                                      expected_resource="agentsentry-monitored") is None


def test_no_safe_fix_does_not_propose_a_change():
    decision = ReasoningService._validate(
        _reply(action=ACTION_NO_SAFE_FIX), expected_resource="agentsentry-monitored"
    )
    assert decision is not None
    assert decision.proposes_change is False


def test_low_confidence_does_not_propose_a_change():
    decision = ReasoningService._validate(
        _reply(confidence="low"), expected_resource="agentsentry-monitored"
    )
    assert decision is not None
    assert decision.proposes_change is False


# --------------------------------------------------------------------------- #
# Availability and failure isolation
# --------------------------------------------------------------------------- #
def test_reasoning_is_disabled_without_a_secret_name():
    service = ReasoningService(_settings(llm_secret_name=""))
    assert service.available is False
    assert service.analyze(
        resource_id="t", resource_type="AWS::DynamoDB::Table", metric_name="ThrottledRequests",
        namespace="AWS/DynamoDB", threshold=1.0, facts={},
    ) is None


def test_missing_secret_disables_reasoning_without_raising(monkeypatch):
    """A broken secret must degrade to the deterministic path, not crash."""
    service = ReasoningService(_settings(llm_secret_name="agentsentry/llm"))
    assert service.available is False  # no real AWS creds in the test environment


def test_evidence_prompt_contains_the_measured_numbers():
    prompt = ReasoningService._format_evidence(
        resource_id="agentsentry-monitored",
        resource_type="AWS::DynamoDB::Table",
        metric_name="ThrottledRequests",
        namespace="AWS/DynamoDB",
        threshold=1.0,
        facts={"billing_mode": "PROVISIONED", "wcu": 1, "rcu": 1, "throttled_15m": 105.0},
        docs=[{"title": "On-demand mode", "excerpt": "Scales automatically."}],
    )
    assert "agentsentry-monitored" in prompt
    assert "PROVISIONED" in prompt
    assert "105" in prompt
    assert "On-demand mode" in prompt
    # The model is told which resource it must echo, so validation can pin it.
    assert "must echo back" in prompt


# --------------------------------------------------------------------------- #
# Credential store selection (Parameter Store is free; Secrets Manager is not)
# --------------------------------------------------------------------------- #
def _fake_boto3(session_cls):
    """Stand in for the boto3 module.

    The service imports boto3 lazily inside the function, so the substitution has
    to happen in sys.modules rather than on the service module.
    """
    return type("boto3", (), {"Session": session_cls})


def test_leading_slash_selects_parameter_store(monkeypatch):
    """A "/" prefix must read SSM, so the free standard tier is used."""
    calls: list[str] = []

    class _SSM:
        def get_parameter(self, Name, WithDecryption):  # noqa: N803
            calls.append(f"ssm:{Name}:{WithDecryption}")
            return {"Parameter": {"Value": json.dumps({
                "aws_access_key_id": "AKIAEXAMPLE",
                "aws_secret_access_key": "shhh",
                "region": "ap-south-1",
                "model_id": "global.anthropic.claude-sonnet-4-6",
            })}}

    class _Session:
        def __init__(self, **_kwargs):
            pass

        def client(self, name, **_kwargs):
            calls.append(f"client:{name}")
            assert name == "ssm", "must not touch Secrets Manager for a /-prefixed name"
            return _SSM()

    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(_Session))
    service = ReasoningService(_settings(llm_secret_name="/agentsentry/llm"))
    config = service._load_config()

    assert config is not None
    assert config["model_id"] == "global.anthropic.claude-sonnet-4-6"
    assert config["region"] == "ap-south-1"
    assert "client:ssm" in calls
    assert "ssm:/agentsentry/llm:True" in calls  # decryption requested


def test_name_without_slash_selects_secrets_manager(monkeypatch):
    seen: list[str] = []

    class _SM:
        def get_secret_value(self, SecretId):  # noqa: N803
            seen.append(SecretId)
            return {"SecretString": json.dumps({
                "aws_access_key_id": "AKIAEXAMPLE",
                "aws_secret_access_key": "shhh",
                "region": "us-east-1",
                "model_id": "amazon.nova-micro-v1:0",
            })}

    class _Session:
        def __init__(self, **_kwargs):
            pass

        def client(self, name, **_kwargs):
            assert name == "secretsmanager"
            return _SM()

    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(_Session))
    service = ReasoningService(_settings(llm_secret_name="agentsentry/llm"))

    assert service._load_config() is not None
    assert seen == ["agentsentry/llm"]


def test_incomplete_credentials_disable_reasoning(monkeypatch):
    """Missing model_id must disable reasoning rather than half-configure it."""
    class _SSM:
        def get_parameter(self, Name, WithDecryption):  # noqa: N803
            return {"Parameter": {"Value": json.dumps({
                "aws_access_key_id": "AKIAEXAMPLE",
                "aws_secret_access_key": "shhh",
                "region": "ap-south-1",
            })}}

    class _Session:
        def __init__(self, **_kwargs):
            pass

        def client(self, name, **_kwargs):
            return _SSM()

    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(_Session))
    service = ReasoningService(_settings(llm_secret_name="/agentsentry/llm"))

    assert service._load_config() is None
