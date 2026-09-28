"""Tests for the AWS MCP Server client and the pull-request report.

The MCP client talks to the Agent Toolkit endpoint at runtime to ground each
recommendation in current AWS documentation. It must never raise into the
remediation pipeline: losing a citation is acceptable, losing the incident is not.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.models import AuditCall, CostDelta, Incident, IncidentStatus, PullRequest, Severity
from app.services.github_service import GitHubService
from app.services.mcp_service import McpDocsService
from config import Settings


def _settings(**overrides) -> Settings:
    base = dict(use_mock_data=True, aws_region="us-east-1")
    base.update(overrides)
    return Settings(**base)


class _Resp:
    def __init__(self, body: str, content_type="application/json"):
        self.text = body
        self.headers = {"content-type": content_type}

    def json(self):
        return json.loads(self.text)


def _tool_payload(items: list[dict]) -> dict:
    """Shape the MCP server actually returns: JSON encoded inside a text block."""
    inner = json.dumps({"content": {"result": items}})
    return {"result": {"content": [{"text": inner}]}}


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #
def test_parses_plain_json_response():
    parsed = McpDocsService._parse(_Resp('{"result": {"ok": true}}'))
    assert parsed == {"result": {"ok": True}}


def test_parses_server_sent_events_response():
    """The endpoint may reply as SSE rather than JSON."""
    sse = 'event: message\ndata: {"result": {"ok": true}}\n\n'
    parsed = McpDocsService._parse(_Resp(sse, "text/event-stream"))
    assert parsed == {"result": {"ok": True}}


def test_unparseable_response_yields_empty_dict_not_an_exception():
    assert McpDocsService._parse(_Resp("<html>nope</html>")) == {}


def test_extracts_title_url_and_excerpt():
    data = _tool_payload([
        {"title": "DynamoDB on-demand capacity mode",
         "url": "https://docs.aws.amazon.com/x",
         "context": "Amazon DynamoDB on-demand scales automatically."},
    ])
    results = McpDocsService._extract_results(data, limit=3)

    assert len(results) == 1
    assert results[0]["title"] == "DynamoDB on-demand capacity mode"
    assert results[0]["url"] == "https://docs.aws.amazon.com/x"
    assert "scales automatically" in results[0]["excerpt"]


def test_strips_private_use_glyphs_from_documentation_text():
    """AWS doc pages embed link icons that would render as junk in a PR."""
    data = _tool_payload([{"title": "Billing\uf0c1", "url": "u", "context": "Text\uf0c1 here"}])
    results = McpDocsService._extract_results(data, limit=3)

    assert "\uf0c1" not in results[0]["title"]
    assert "\uf0c1" not in results[0]["excerpt"]
    assert results[0]["title"] == "Billing"


def test_collapses_whitespace_in_excerpts():
    data = _tool_payload([{"title": "t", "url": "u", "context": "line one\n\n   line two"}])
    assert McpDocsService._extract_results(data, limit=3)[0]["excerpt"] == "line one line two"


def test_respects_the_result_limit():
    data = _tool_payload([{"title": f"d{i}", "url": "u", "context": "c"} for i in range(10)])
    assert len(McpDocsService._extract_results(data, limit=3)) == 3


def test_endpoint_and_signing_service_follow_the_region():
    svc = McpDocsService(_settings(aws_region="eu-central-1"))
    assert svc._endpoint == "https://aws-mcp.eu-central-1.api.aws/mcp"  # noqa: SLF001
    assert svc._service == "aws-mcp"  # noqa: SLF001


# --------------------------------------------------------------------------- #
# Pull-request report
# --------------------------------------------------------------------------- #
def _incident() -> Incident:
    now = datetime.now(timezone.utc)
    return Incident(
        id="INC-1790566592",
        title="DynamoDB throttling detected",
        resource_id="agentsentry-monitored",
        resource_type="AWS::DynamoDB::Table",
        metric_name="ThrottledRequests",
        severity=Severity.HIGH,
        status=IncidentStatus.PR_OPEN,
        detected_at=now,
        updated_at=now,
        audit_calls=[
            AuditCall(event_name="DescribeTable", event_time=now,
                      aws_service="dynamodb.amazonaws.com", read_only=True, principal="p"),
            AuditCall(event_name="GetMetricStatistics", event_time=now,
                      aws_service="monitoring.amazonaws.com", read_only=True, principal="p"),
        ],
    )


def _body(**overrides) -> str:
    gh = GitHubService(_settings())
    kwargs = dict(
        diagnosis="121 throttled PutItem requests observed.",
        cdk_diff="[-] BillingMode: PROVISIONED\n[+] BillingMode: PAY_PER_REQUEST",
        cost_delta=CostDelta(before_monthly_usd=0.57, after_monthly_usd=0.0),
        rollback="Revert the commit and redeploy.",
        incident=_incident(),
        facts={"billing_mode": "PROVISIONED", "rcu": 1, "wcu": 1, "throttled_15m": 121.0},
        impact="Writes were refused.",
        why_this_fix="Removes the capacity ceiling.",
        alternatives="| Option | Assessment |",
        verification="Re-reads the live metric.",
        audit_calls=_incident().audit_calls,
        docs=[{"title": "On-demand mode", "url": "https://docs.aws.amazon.com/x",
               "excerpt": "Scales automatically."}],
    )
    kwargs.update(overrides)
    return gh.build_pr_body(**kwargs)


def test_report_contains_every_review_section():
    body = _body()
    for section in (
        "Incident summary", "What went wrong", "Evidence gathered",
        "Why this matters", "The fix in this pull request",
        "AWS documentation consulted", "Alternatives considered",
        "Cost impact", "How this will be verified", "Rollback plan",
        "Read-only audit trail",
    ):
        assert section in body, f"PR report is missing: {section}"


def test_report_cites_the_documentation_it_consulted():
    body = _body()
    assert "https://docs.aws.amazon.com/x" in body
    assert "AWS MCP Server" in body


def test_cost_saving_is_signed_correctly():
    """A saving must read -$0.57, never $-0.57."""
    body = _body()
    assert "-$0.57/mo" in body
    assert "$-0.57" not in body


def test_cost_increase_is_signed_correctly():
    body = _body(cost_delta=CostDelta(before_monthly_usd=0.0, after_monthly_usd=1.25))
    assert "+$1.25/mo" in body


def test_audit_trail_marks_calls_read_only():
    body = _body()
    assert "DescribeTable" in body
    assert "GetMetricStatistics" in body
    assert "Read-only" in body


def test_report_states_that_a_human_must_merge():
    body = _body()
    assert "human" in body.lower()
    assert "merg" in body.lower()


def test_report_renders_without_optional_sections():
    """Missing docs or narrative must not break the report."""
    body = _body(docs=None, impact="", alternatives="", verification="")
    assert "What went wrong" in body
    assert "AWS documentation consulted" not in body


def test_github_is_not_considered_configured_without_a_real_repo():
    assert GitHubService(_settings(github_token="t", github_repo="your-org/x")).configured is False
    assert GitHubService(_settings(github_token=None, github_repo="me/real")).configured is False
    assert GitHubService(_settings(github_token="t", github_repo="me/real")).configured is True
