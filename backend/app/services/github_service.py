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
        self, diagnosis: str, cdk_diff: str, cost_delta: CostDelta, rollback: str
    ) -> str:
        """Compose a reviewable PR description with all supporting evidence."""
        delta = cost_delta.difference_usd
        sign = "+" if delta >= 0 else ""
        return (
            "## AgentSentry AI — automated remediation\n\n"
            "This pull request was opened automatically by **AgentSentry AI** after it detected a "
            "live infrastructure incident, inspected the affected resource read-only, and derived "
            "the fix from the observed data.\n\n"
            f"### Diagnosis\n{diagnosis}\n\n"
            "### Proposed change (`cdk diff`)\n"
            f"```\n{cdk_diff}\n```\n\n"
            "### Cost delta\n"
            "| Before | After | Difference |\n"
            "| --- | --- | --- |\n"
            f"| ${cost_delta.before_monthly_usd:.2f}/mo | ${cost_delta.after_monthly_usd:.2f}/mo "
            f"| {sign}${delta:.2f}/mo |\n\n"
            "### Rollback plan\n"
            f"{rollback}\n\n"
            "---\n"
            "_Read-only by construction, human-in-the-loop by design. The agent only inspected "
            "AWS (Describe / Get / List) and proposed this change — a human must review and merge._"
        )

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
