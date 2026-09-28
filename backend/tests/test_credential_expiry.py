"""Tests for the scheduled credential-expiry handler.

The dangerous failure here is deleting the credentials *before* judging ends, so
most of these pin the retain path: a future date, a missing date, and a malformed
date must all leave the credentials alone.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import lambda_credential_expiry as expiry


def _iso(days_from_now: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days_from_now)).isoformat()


class _FakeSSM:
    def __init__(self, error_code: str | None = None):
        self.deleted: list[str] = []
        self._error_code = error_code

    def delete_parameter(self, Name):  # noqa: N803
        if self._error_code:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": self._error_code}}, "DeleteParameter")
        self.deleted.append(Name)


def _install_fake(monkeypatch, client):
    """Substitute boto3 in sys.modules; the handler imports it lazily."""
    fake = type("boto3", (), {"client": staticmethod(lambda _name: client)})
    monkeypatch.setitem(sys.modules, "boto3", fake)
    return client


# --------------------------------------------------------------------------- #
# Retain paths: nothing may be deleted early
# --------------------------------------------------------------------------- #
def test_credentials_are_retained_before_the_expiry_date(monkeypatch):
    client = _install_fake(monkeypatch, _FakeSSM())
    monkeypatch.setenv("LLM_SECRET_NAME", "/agentsentry/llm")
    monkeypatch.setenv("LLM_CREDENTIAL_EXPIRY", _iso(10))

    result = expiry.handler({}, None)

    assert result["action"] == "retained"
    assert result["days_remaining"] == 10
    assert client.deleted == []


def test_malformed_expiry_date_never_deletes(monkeypatch):
    """A typo in the date must not be read as 'expired'."""
    client = _install_fake(monkeypatch, _FakeSSM())
    monkeypatch.setenv("LLM_SECRET_NAME", "/agentsentry/llm")
    monkeypatch.setenv("LLM_CREDENTIAL_EXPIRY", "31-10-2026")

    result = expiry.handler({}, None)

    assert result["action"] == "skipped"
    assert client.deleted == []


def test_missing_configuration_is_a_no_op(monkeypatch):
    client = _install_fake(monkeypatch, _FakeSSM())
    monkeypatch.delenv("LLM_SECRET_NAME", raising=False)
    monkeypatch.delenv("LLM_CREDENTIAL_EXPIRY", raising=False)

    assert expiry.handler({}, None)["action"] == "skipped"
    assert client.deleted == []


# --------------------------------------------------------------------------- #
# Delete paths
# --------------------------------------------------------------------------- #
def test_parameter_is_deleted_on_the_expiry_date(monkeypatch):
    """Boundary: the expiry date itself counts as expired."""
    client = _install_fake(monkeypatch, _FakeSSM())
    monkeypatch.setenv("LLM_SECRET_NAME", "/agentsentry/llm")
    monkeypatch.setenv("LLM_CREDENTIAL_EXPIRY", _iso(0))

    result = expiry.handler({}, None)

    assert result["action"] == "deleted"
    assert client.deleted == ["/agentsentry/llm"]


def test_parameter_is_deleted_after_the_expiry_date(monkeypatch):
    client = _install_fake(monkeypatch, _FakeSSM())
    monkeypatch.setenv("LLM_SECRET_NAME", "/agentsentry/llm")
    monkeypatch.setenv("LLM_CREDENTIAL_EXPIRY", _iso(-5))

    assert expiry.handler({}, None)["action"] == "deleted"
    assert client.deleted == ["/agentsentry/llm"]


def test_already_deleted_is_reported_not_raised(monkeypatch):
    """Running daily after expiry must stay green rather than erroring."""
    _install_fake(monkeypatch, _FakeSSM(error_code="ParameterNotFound"))
    monkeypatch.setenv("LLM_SECRET_NAME", "/agentsentry/llm")
    monkeypatch.setenv("LLM_CREDENTIAL_EXPIRY", _iso(-1))

    assert expiry.handler({}, None)["action"] == "already absent"


def test_unexpected_delete_error_is_not_swallowed(monkeypatch):
    """A permissions problem must surface, not look like success."""
    from botocore.exceptions import ClientError

    _install_fake(monkeypatch, _FakeSSM(error_code="AccessDeniedException"))
    monkeypatch.setenv("LLM_SECRET_NAME", "/agentsentry/llm")
    monkeypatch.setenv("LLM_CREDENTIAL_EXPIRY", _iso(-1))

    try:
        expiry.handler({}, None)
    except ClientError:
        pass
    else:
        raise AssertionError("AccessDenied should not be treated as success")


def test_name_without_slash_uses_secrets_manager(monkeypatch):
    class _FakeSM:
        def __init__(self):
            self.deleted: list[tuple[str, bool]] = []

        def delete_secret(self, SecretId, ForceDeleteWithoutRecovery):  # noqa: N803
            self.deleted.append((SecretId, ForceDeleteWithoutRecovery))

    client = _install_fake(monkeypatch, _FakeSM())
    monkeypatch.setenv("LLM_SECRET_NAME", "agentsentry/llm")
    monkeypatch.setenv("LLM_CREDENTIAL_EXPIRY", _iso(-1))

    assert expiry.handler({}, None)["action"] == "deleted"
    assert client.deleted == [("agentsentry/llm", True)]
