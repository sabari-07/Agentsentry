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
from datetime import datetime, timezone

import httpx

from app.models import CostDelta
from config import Settings

logger = logging.getLogger("agentsentry.github")

_GITHUB_API = "https://api.github.com"


class GitHubService:
    """Thin GitHub REST client scoped to creating remediation PRs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Config helpers
    # ------------------------------------------------------------------ #
    @property
    def configured(self) -> bool:
        """True when a token and a real repo are configured."""
        s = self._settings
        return bool(s.github_token) and "your-org" not in s.github_repo

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo_url(self, path: str) -> str:
        return f"{_GITHUB_API}/repos/{self._settings.github_repo}{path}"

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
            "and derived the fix from the data it actually observed. No change has been applied — "
            "this PR proposes the fix for human review."
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
        fix.append("Proposed infrastructure change (`cdk diff`):\n")
        fix.append(f"```\n{cdk_diff}\n```")
        parts.append("\n".join(fix))

        # --- Alternatives considered ---
        if alternatives:
            parts.append(f"### 6. Alternatives considered\n\n{alternatives}")

        # --- Cost ---
        parts.append(
            "### 7. Cost impact\n\n"
            "| Before | After | Difference |\n| --- | --- | --- |\n"
            f"| ${cost_delta.before_monthly_usd:.2f}/mo | ${cost_delta.after_monthly_usd:.2f}/mo "
            f"| {delta_str} |\n\n"
            "_Estimates based on the observed configuration and current AWS on-demand pricing for "
            "this region. Actual cost varies with traffic._"
        )

        # --- How to verify ---
        if verification:
            parts.append(f"### 8. How this will be verified after merge\n\n{verification}")

        # --- Rollback ---
        parts.append(f"### 9. Rollback plan\n\n{rollback}")

        # --- Audit trail ---
        if audit_calls:
            rows = ["### 10. Read-only audit trail\n"]
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
            "Merging this PR is a human decision; the change is applied only after merge."
        )

        return "\n\n".join(parts)

    # ------------------------------------------------------------------ #
    # Full PR flow: branch -> commit -> PR
    # ------------------------------------------------------------------ #
    def create_remediation_pr(
        self,
        *,
        title: str,
        branch: str,
        body: str,
        file_path: str,
        file_content: str,
        commit_message: str,
    ) -> dict | None:
        """Create a branch, commit a real file change, and open a PR.

        Returns the GitHub PR payload, or None if GitHub is not configured or the
        flow fails (failures are logged and never raise into the caller).
        """
        if not self.configured:
            logger.info("GitHub not configured; skipping real PR creation.")
            return None

        base = self._settings.github_base_branch
        # Make the branch unique so repeated incidents don't collide.
        unique_branch = f"{branch}-{int(datetime.now(timezone.utc).timestamp())}"

        try:
            with httpx.Client(timeout=30, headers=self._headers()) as client:
                # 1. Head SHA of the base branch.
                ref = client.get(self._repo_url(f"/git/ref/heads/{base}"))
                ref.raise_for_status()
                base_sha = ref.json()["object"]["sha"]

                # 2. Create the remediation branch.
                created = client.post(
                    self._repo_url("/git/refs"),
                    json={"ref": f"refs/heads/{unique_branch}", "sha": base_sha},
                )
                created.raise_for_status()

                # 3. Commit the file change on that branch (create or update).
                existing_sha = None
                probe = client.get(
                    self._repo_url(f"/contents/{file_path}"), params={"ref": unique_branch}
                )
                if probe.status_code == 200:
                    existing_sha = probe.json().get("sha")

                payload = {
                    "message": commit_message,
                    "content": base64.b64encode(file_content.encode()).decode(),
                    "branch": unique_branch,
                }
                if existing_sha:
                    payload["sha"] = existing_sha
                put = client.put(self._repo_url(f"/contents/{file_path}"), json=payload)
                put.raise_for_status()

                # 4. Open the PR.
                pr = client.post(
                    self._repo_url("/pulls"),
                    json={"title": title, "head": unique_branch, "base": base, "body": body},
                )
                pr.raise_for_status()
                data = pr.json()

            logger.info("Opened PR #%s: %s", data["number"], data["html_url"])
            return data
        except httpx.HTTPStatusError as e:
            logger.error(
                "GitHub API error (%s): %s", e.response.status_code, e.response.text[:300]
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to create remediation PR")
        return None
