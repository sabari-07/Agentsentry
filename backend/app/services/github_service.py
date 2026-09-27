"""GitHub service for opening remediation Pull Requests.

The PR is the deliverable artifact: it carries the CDK change, a ``cdk diff``,
a cost delta and a rollback plan. Merging is always a human action; this service
never merges.
"""
from __future__ import annotations

import logging

import httpx

from app.models import CostDelta, PullRequest
from config import Settings

logger = logging.getLogger("agentsentry.github")

_GITHUB_API = "https://api.github.com"


class GitHubService:
    """Thin GitHub REST client scoped to opening remediation PRs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def build_pr_body(self, diagnosis: str, cdk_diff: str, cost_delta: CostDelta, rollback: str) -> str:
        """Compose a reviewable PR description with all supporting evidence."""
        delta = cost_delta.difference_usd
        sign = "+" if delta >= 0 else ""
        return (
            "## AgentSentry AI — automated remediation\n\n"
            f"### Diagnosis\n{diagnosis}\n\n"
            "### Proposed change (`cdk diff`)\n"
            f"```\n{cdk_diff}\n```\n\n"
            "### Cost delta\n"
            f"| Before | After | Difference |\n"
            f"| --- | --- | --- |\n"
            f"| ${cost_delta.before_monthly_usd:.2f}/mo | ${cost_delta.after_monthly_usd:.2f}/mo "
            f"| {sign}${delta:.2f}/mo |\n\n"
            "### Rollback plan\n"
            f"{rollback}\n\n"
            "---\n"
            "_Read-only by construction, human-in-the-loop by design. "
            "This PR was proposed by an agent and must be reviewed and merged by a human._"
        )

    def open_pull_request(
        self,
        *,
        title: str,
        branch: str,
        body: str,
    ) -> PullRequest | None:
        """Open a PR from ``branch`` into the configured base branch.

        Assumes ``branch`` already exists with the committed CDK change (created
        by the coding agent). Returns None if GitHub is not configured.
        """
        if not self._settings.github_token:
            logger.warning("GITHUB_TOKEN not configured; cannot open PR.")
            return None

        url = f"{_GITHUB_API}/repos/{self._settings.github_repo}/pulls"
        payload = {
            "title": title,
            "head": branch,
            "base": self._settings.github_base_branch,
            "body": body,
        }
        with httpx.Client(timeout=20) as client:
            response = client.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()

        logger.info("Opened PR #%s: %s", data["number"], data["html_url"])
        return data  # caller maps to PullRequest with cost_delta/diff/rollback attached
