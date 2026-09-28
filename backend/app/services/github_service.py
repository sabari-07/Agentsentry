"""GitHub service for opening remediation Pull Requests.

The PR is the deliverable artifact: it carries a real Infrastructure-as-Code
change, a ``cdk diff``, a cost delta and a rollback plan. This service can:

  1. read the base branch head,
  2. create a remediation branch,
  3. commit a real file change (the CDK capacity fix),
  4. open a Pull Request describing the evidence.

Merging is always a human action; this service never merges.
"""
from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from datetime import datetime, timezone

import httpx

from app.models import CostDelta
from config import Settings

logger = logging.getLogger("agentsentry.github")

_GITHUB_API = "https://api.github.com"


class GitHubService:
    """Thin GitHub REST client scoped to creating remediation PRs."""

    # ------------------------------------------------------------------ #
    # Config helpers
    # ------------------------------------------------------------------ #
    def __init__(self, settings: Settings, repo: str | None = None) -> None:  # noqa: D107
        self._settings = settings
        # A per-resource repository override for PR routing. A mapped target
        # must use the supported IaC layout and provide its own deployment/
        # verification integration; routing alone does not deploy another repo.
        self._repo = repo or settings.github_repo

    def for_repo(self, repo: str) -> "GitHubService":
        """Return a client bound to a different repository."""
        return GitHubService(self._settings, repo)

    @property
    def repo(self) -> str:
        return self._repo

    @property
    def configured(self) -> bool:
        """True when a token and a real repo are configured."""
        return bool(self._settings.github_token) and "your-org" not in self._repo

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo_url(self, path: str) -> str:
        return f"{_GITHUB_API}/repos/{self._repo}{path}"

    # ------------------------------------------------------------------ #
    # PR body
    # ------------------------------------------------------------------ #
    def build_pr_body(
        self,
        diagnosis: str,
        cdk_diff: str,
        cost_delta: CostDelta,
        rollback: str,
        *,
        incident=None,
        facts: dict | None = None,
        impact: str = "",
        why_this_fix: str = "",
        alternatives: str = "",
        verification: str = "",
        audit_calls: list | None = None,
        docs: list | None = None,
        changed_files: list[str] | None = None,
    ) -> str:
        """Compose a detailed, reviewable incident report as the PR description."""
        delta = cost_delta.difference_usd
        # Format as -$0.57 / +$0.57 rather than $-0.57.
        delta_str = f"{'+' if delta >= 0 else '-'}${abs(delta):.2f}/mo"
        facts = facts or {}
        audit_calls = audit_calls or []

        parts: list[str] = []

        parts.append(
            "## AgentSentry AI — automated remediation\n\n"
            "This pull request was opened automatically by **AgentSentry AI** after it detected a "
            "live infrastructure incident in AWS, inspected the affected resource **read-only**, "
            "and derived the fix from the data it actually observed. The branch contains the "
            "proposed source changes, but no change has been applied to AWS — a human must review "
            "and merge this PR, then the merged infrastructure code must be deployed."
        )

        # --- Incident summary table ---
        if incident is not None:
            parts.append(
                "### 1. Incident summary\n\n"
                "| Field | Value |\n| --- | --- |\n"
                f"| Incident ID | `{incident.id}` |\n"
                f"| Resource | `{incident.resource_id}` |\n"
                f"| Resource type | `{incident.resource_type}` |\n"
                f"| Breaching metric | `{incident.metric_name}` |\n"
                f"| Severity | **{incident.severity.value}** |\n"
                f"| Detected at | {incident.detected_at.isoformat()} |\n"
                f"| Detection path | CloudWatch alarm → EventBridge → incident Lambda |"
            )

        # --- What went wrong ---
        parts.append(f"### 2. What went wrong\n\n{diagnosis}")

        # --- Evidence gathered ---
        if facts:
            ev = ["### 3. Evidence gathered from the live account\n"]
            ev.append("| Observation | Value |\n| --- | --- |")
            if facts.get("billing_mode"):
                ev.append(f"| Billing mode | `{facts['billing_mode']}` |")
            if facts.get("rcu") is not None:
                ev.append(f"| Provisioned read capacity (RCU) | {facts['rcu']} |")
            if facts.get("wcu") is not None:
                ev.append(f"| Provisioned write capacity (WCU) | {facts['wcu']} |")
            if facts.get("throttled_15m") is not None:
                ev.append(
                    f"| Throttled `PutItem` requests (last 15 min) | **{facts['throttled_15m']:g}** |"
                )
            if facts.get("item_count") is not None:
                ev.append(f"| Approx. item count | {facts['item_count']} |")
            parts.append("\n".join(ev))

        # --- Impact ---
        if impact:
            parts.append(f"### 4. Why this matters (impact)\n\n{impact}")

        # --- The fix ---
        fix = ["### 5. The fix in this pull request\n"]
        if why_this_fix:
            fix.append(why_this_fix + "\n")
        if changed_files:
            fix.append("The branch commits these reviewable files:\n")
            fix.extend(f"- `{path}`" for path in changed_files)
            fix.append("")
        fix.append("Proposed infrastructure change (`cdk diff`):\n")
        fix.append(f"```\n{cdk_diff}\n```")
        parts.append("\n".join(fix))

        # --- AWS documentation consulted (via the Agent Toolkit MCP server) ---
        if docs:
            d = ["### 6. AWS documentation consulted\n"]
            d.append(
                "The agent queried the **AWS MCP Server (Agent Toolkit for AWS)** at runtime and "
                "grounded this recommendation in the following official AWS documentation:\n"
            )
            for doc in docs:
                title = doc.get("title", "AWS documentation")
                url = doc.get("url", "")
                excerpt = doc.get("excerpt", "")
                d.append(f"- **[{title}]({url})**" if url else f"- **{title}**")
                if excerpt:
                    d.append(f"  > {excerpt}")
            parts.append("\n".join(d))

        # --- Alternatives considered ---
        if alternatives:
            parts.append(f"### 7. Alternatives considered\n\n{alternatives}")

        # --- Cost ---
        parts.append(
            "### 8. Cost impact\n\n"
            "| Before | After | Difference |\n| --- | --- | --- |\n"
            f"| ${cost_delta.before_monthly_usd:.2f}/mo | ${cost_delta.after_monthly_usd:.2f}/mo "
            f"| {delta_str} |\n\n"
            "_Estimates based on the observed configuration and current AWS on-demand pricing for "
            "this region. Actual cost varies with traffic._"
        )

        # --- How to verify ---
        if verification:
            parts.append(f"### 9. How this will be verified after deployment\n\n{verification}")

        # --- Rollback ---
        parts.append(f"### 10. Rollback plan\n\n{rollback}")

        # --- Audit trail ---
        if audit_calls:
            rows = ["### 11. Read-only audit trail\n"]
            rows.append(
                "Every AWS API call the agent made while investigating this incident:\n"
            )
            rows.append("| API call | Service | Read-only |\n| --- | --- | --- |")
            for c in audit_calls:
                svc = c.aws_service.replace(".amazonaws.com", "")
                rows.append(f"| `{c.event_name}` | {svc} | {'✅' if c.read_only else '❌'} |")
            rows.append(
                "\nThese are management events and are independently verifiable in "
                "**CloudTrail → Event history**."
            )
            parts.append("\n".join(rows))

        parts.append(
            "---\n"
            "**Safety model:** read-only by construction, human-in-the-loop by design. The agent "
            "only issued `Describe*` / `Get*` / `List*` calls and never mutated infrastructure. "
            "Merging this PR is a human decision; AWS changes only after the merged infrastructure "
            "code is deployed."
        )

        return "\n\n".join(parts)

    # ------------------------------------------------------------------ #
    # Comment the verified outcome back onto the PR
    # ------------------------------------------------------------------ #
    def comment_verification(self, pr_number: int, verification, incident_id: str) -> bool:
        """Post the verification result as a comment on the remediation PR.

        This closes the loop publicly: the same PR that proposed the fix now
        carries the evidence of whether it actually worked.
        """
        if not self.configured or not pr_number:
            return False

        healthy = verification.healthy
        icon = "✅" if healthy else "❌"
        headline = (
            "Verified: the fix resolved the incident"
            if healthy
            else "Not verified: the metric is still breaching"
        )
        body = (
            f"## {icon} AgentSentry AI — post-deploy verification\n\n"
            f"**{headline}**\n\n"
            f"After deployment, AgentSentry AI re-read the live CloudWatch metric for this "
            f"resource. This result is measured, not assumed.\n\n"
            "| Check | Value |\n| --- | --- |\n"
            f"| Incident | `{incident_id}` |\n"
            f"| Metric | `{verification.metric_name}` |\n"
            f"| Observed value | **{verification.observed_value:g}** |\n"
            f"| Threshold | {verification.threshold:g} |\n"
            f"| Observation window | {verification.window_minutes} minutes |\n"
            f"| Verified at | {verification.verified_at.isoformat()} |\n"
            f"| Outcome | **{'RESOLVED_VERIFIED' if healthy else 'FAILED'}** |\n\n"
            f"{verification.summary}\n"
        )
        try:
            with httpx.Client(timeout=20, headers=self._headers()) as client:
                resp = client.post(
                    self._repo_url(f"/issues/{pr_number}/comments"), json={"body": body}
                )
                resp.raise_for_status()
            logger.info("Posted verification comment on PR #%s", pr_number)
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to comment verification on PR #%s", pr_number)
            return False

    # ------------------------------------------------------------------ #
    # Full PR flow: branch -> commit -> PR
    # ------------------------------------------------------------------ #
    def create_remediation_pr(
        self,
        *,
        title: str,
        branch: str,
        body: str,
        file_contents: dict[str, str],
        file_transformers: dict[str, Callable[[str], str]],
        commit_message: str,
    ) -> dict | None:
        """Create one atomic remediation commit and open a pull request.

        ``file_contents`` contains new files such as the incident report.
        ``file_transformers`` maps an existing repository path to a guarded
        source transformation. Every transformer must return changed content;
        otherwise the method fails closed rather than opening a PR that only
        describes a fix.
        """
        if not self.configured:
            logger.info("GitHub not configured; skipping real PR creation.")
            return None
        if not file_contents and not file_transformers:
            logger.error("Refusing to open a remediation PR without file changes.")
            return None

        base = self._settings.github_base_branch
        unique_branch = f"{branch}-{int(datetime.now(timezone.utc).timestamp())}"

        try:
            with httpx.Client(timeout=30, headers=self._headers()) as client:
                # Resolve the immutable base commit and its tree. Building the
                # complete commit before creating the branch avoids a partially
                # updated remediation branch if any file transformation fails.
                ref = client.get(self._repo_url(f"/git/ref/heads/{base}"))
                ref.raise_for_status()
                base_sha = ref.json()["object"]["sha"]

                commit = client.get(self._repo_url(f"/git/commits/{base_sha}"))
                commit.raise_for_status()
                base_tree_sha = commit.json()["tree"]["sha"]

                resolved_contents = dict(file_contents)
                for path, transform in file_transformers.items():
                    source_response = client.get(
                        self._repo_url(f"/contents/{path}"), params={"ref": base_sha}
                    )
                    source_response.raise_for_status()
                    source_payload = source_response.json()
                    if source_payload.get("encoding") != "base64":
                        raise ValueError(f"Unsupported GitHub encoding for {path}")
                    source = base64.b64decode(source_payload["content"]).decode("utf-8")
                    transformed = transform(source)
                    if transformed == source:
                        raise ValueError(f"Remediation transformer made no change to {path}")
                    resolved_contents[path] = transformed

                # Git's data API lets the real IaC edit and its incident report
                # land in a single commit, so reviewers never see half a fix.
                tree_entries = []
                for path, content in resolved_contents.items():
                    blob = client.post(
                        self._repo_url("/git/blobs"),
                        json={"content": content, "encoding": "utf-8"},
                    )
                    blob.raise_for_status()
                    tree_entries.append(
                        {
                            "path": path,
                            "mode": "100644",
                            "type": "blob",
                            "sha": blob.json()["sha"],
                        }
                    )

                tree = client.post(
                    self._repo_url("/git/trees"),
                    json={"base_tree": base_tree_sha, "tree": tree_entries},
                )
                tree.raise_for_status()

                new_commit = client.post(
                    self._repo_url("/git/commits"),
                    json={
                        "message": commit_message,
                        "tree": tree.json()["sha"],
                        "parents": [base_sha],
                    },
                )
                new_commit.raise_for_status()
                remediation_sha = new_commit.json()["sha"]

                created = client.post(
                    self._repo_url("/git/refs"),
                    json={
                        "ref": f"refs/heads/{unique_branch}",
                        "sha": remediation_sha,
                    },
                )
                created.raise_for_status()

                pr = client.post(
                    self._repo_url("/pulls"),
                    json={"title": title, "head": unique_branch, "base": base, "body": body},
                )
                pr.raise_for_status()
                data = pr.json()

            logger.info(
                "Opened PR #%s with %d changed files: %s",
                data["number"], len(resolved_contents), data["html_url"],
            )
            return data
        except httpx.HTTPStatusError as e:
            logger.error(
                "GitHub API error (%s): %s", e.response.status_code, e.response.text[:300]
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to create remediation PR")
        return None
