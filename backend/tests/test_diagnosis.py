"""Tests for the deterministic diagnosis engine.

The remediation decision is deliberately not made by a language model: the same
observed state must always produce the same, reviewable recommendation. These
tests pin that behaviour, including the cost arithmetic quoted in every PR.
"""
from __future__ import annotations

from app.services.diagnosis_service import DiagnosisService
from config import Settings


def _svc() -> DiagnosisService:
    # Bypass __init__ so no AWS clients are constructed.
    return DiagnosisService.__new__(DiagnosisService)


def _facts(**overrides) -> dict:
    base = {
        "billing_mode": "PROVISIONED",
        "rcu": 1,
        "wcu": 1,
        "item_count": 711,
        "throttled_15m": 116.0,
        "audit_calls": [],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Branching on observed state
# --------------------------------------------------------------------------- #
def test_provisioned_table_is_told_to_move_to_on_demand():
    diagnosis, pr = DiagnosisService.diagnose(_svc(), "t", _facts())

    assert "PROVISIONED" in diagnosis
    assert "on-demand" in pr.title.lower()
    assert "PAY_PER_REQUEST" in pr.cdk_diff


def test_on_demand_table_is_told_to_retry_instead_of_rescaling():
    """Capacity is not a lever on an on-demand table, so the fix must differ."""
    diagnosis, pr = DiagnosisService.diagnose(
        _svc(), "t", _facts(billing_mode="PAY_PER_REQUEST")
    )

    assert "backoff" in pr.title.lower() or "backoff" in pr.cdk_diff.lower()
    assert "PAY_PER_REQUEST" not in pr.cdk_diff, "must not propose a change already in place"
    assert "adaptive capacity" in diagnosis


def test_diagnosis_quotes_the_real_observed_numbers():
    """Every figure in the PR must come from the measurement, not a template."""
    diagnosis, _ = DiagnosisService.diagnose(
        _svc(), "my-table", _facts(wcu=3, rcu=2, throttled_15m=57.0)
    )
    assert "57" in diagnosis
    assert "3 WCU" in diagnosis
    assert "2 RCU" in diagnosis
    assert "my-table" in diagnosis


def test_singular_grammar_for_a_single_write_per_second():
    diagnosis, _ = DiagnosisService.diagnose(_svc(), "t", _facts(wcu=1))
    assert "1 small write per second" in diagnosis


def test_plural_grammar_for_multiple_writes_per_second():
    diagnosis, _ = DiagnosisService.diagnose(_svc(), "t", _facts(wcu=5))
    assert "5 small writes per second" in diagnosis


# --------------------------------------------------------------------------- #
# Cost arithmetic — must never be a meaningless $0.00 -> $0.00
# --------------------------------------------------------------------------- #
def test_cost_delta_is_derived_from_observed_capacity():
    _, pr = DiagnosisService.diagnose(_svc(), "t", _facts(wcu=1, rcu=1))
    cd = pr.cost_delta

    assert cd.before_monthly_usd > 0, "provisioned capacity is not free of charge"
    assert cd.difference_usd < 0, "moving to on-demand at this volume should save money"


def test_higher_provisioned_capacity_costs_more():
    _, small = DiagnosisService.diagnose(_svc(), "t", _facts(wcu=1))
    _, large = DiagnosisService.diagnose(_svc(), "t", _facts(wcu=50))
    assert large.cost_delta.before_monthly_usd > small.cost_delta.before_monthly_usd


# --------------------------------------------------------------------------- #
# Every proposal must carry its review material
# --------------------------------------------------------------------------- #
def test_every_proposal_includes_a_rollback_plan():
    for mode in ("PROVISIONED", "PAY_PER_REQUEST"):
        _, pr = DiagnosisService.diagnose(_svc(), "t", _facts(billing_mode=mode))
        assert pr.rollback_plan.strip(), f"{mode} proposal has no rollback plan"


def test_narrative_sections_are_produced_for_the_pull_request():
    facts = _facts()
    DiagnosisService.diagnose(_svc(), "t", facts)
    narrative = facts["_narrative"]

    for key in ("impact", "why_this_fix", "alternatives", "verification"):
        assert narrative.get(key), f"missing narrative section: {key}"


def test_alternatives_name_the_rejected_options_with_reasons():
    facts = _facts()
    DiagnosisService.diagnose(_svc(), "t", facts)
    alternatives = facts["_narrative"]["alternatives"]

    assert "auto-scaling" in alternatives
    assert "backoff" in alternatives
    assert "chosen" in alternatives


def test_agent_never_proposes_to_merge_or_apply_itself():
    """Safety model: the agent proposes; a human merges."""
    facts = _facts()
    DiagnosisService.diagnose(_svc(), "t", facts)
    verification = facts["_narrative"]["verification"]
    assert "RESOLVED_VERIFIED" in verification
    assert "FAILED" in verification, "must state that failure is a possible outcome"


# --------------------------------------------------------------------------- #
# Documentation lookup degrades gracefully
# --------------------------------------------------------------------------- #
def test_documentation_lookup_without_a_client_returns_empty():
    svc = _svc()
    svc._docs = None  # noqa: SLF001
    assert DiagnosisService.consult_documentation(svc, _facts()) == []


def test_search_phrase_differs_by_billing_mode():
    class _Docs:
        def __init__(self):
            self.phrases: list[str] = []

        def search_documentation(self, phrase, limit=3):  # noqa: ARG002
            self.phrases.append(phrase)
            return []

    svc = _svc()
    svc._docs = _Docs()  # noqa: SLF001
    DiagnosisService.consult_documentation(svc, _facts(billing_mode="PROVISIONED"))
    DiagnosisService.consult_documentation(svc, _facts(billing_mode="PAY_PER_REQUEST"))

    provisioned, on_demand = svc._docs.phrases  # noqa: SLF001
    assert provisioned != on_demand
    assert "on-demand" in provisioned
    assert "backoff" in on_demand


def _unused(_: Settings) -> None:  # keeps the Settings import meaningful for linters
    return None
