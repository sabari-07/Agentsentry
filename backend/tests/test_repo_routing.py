"""Tests for routing a pull request to the repository that owns the resource.

One deployment may watch resources belonging to several projects, so the repo a
remediation lands in has to be a function of the affected resource rather than a
single global setting.
"""
from __future__ import annotations

from app.services.github_service import GitHubService
from config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        use_mock_data=True,
        github_token="t",
        github_repo="org/default-repo",
        resource_repo_map="",
    )
    base.update(overrides)
    return Settings(**base)


def test_unmapped_resource_uses_the_default_repository():
    s = _settings()
    assert s.repo_for_resource("anything") == "org/default-repo"


def test_mapped_resource_routes_to_its_own_repository():
    s = _settings(resource_repo_map="orders=org/orders-infra,users=org/users-infra")
    assert s.repo_for_resource("orders") == "org/orders-infra"
    assert s.repo_for_resource("users") == "org/users-infra"
    assert s.repo_for_resource("payments") == "org/default-repo"


def test_mapping_tolerates_whitespace_and_trailing_separators():
    s = _settings(resource_repo_map=" orders = org/orders-infra , ,")
    assert s.repo_for_resource("orders") == "org/orders-infra"


def test_malformed_entries_are_ignored_rather_than_crashing():
    s = _settings(resource_repo_map="nonsense,,=,orders=org/ok")
    assert s.repo_for_resource("orders") == "org/ok"
    assert s.repo_for_resource("nonsense") == "org/default-repo"


def test_github_client_can_be_rebound_to_another_repository():
    gh = GitHubService(_settings())
    assert gh.repo == "org/default-repo"

    other = gh.for_repo("org/orders-infra")
    assert other.repo == "org/orders-infra"
    assert gh.repo == "org/default-repo", "rebinding must not mutate the original"
    assert "org/orders-infra" in other._repo_url("/pulls")  # noqa: SLF001


def test_configured_reflects_the_bound_repository():
    gh = GitHubService(_settings(github_repo="your-org/agentsentry-ai"))
    assert gh.configured is False, "placeholder repo must not count as configured"
    assert gh.for_repo("org/real").configured is True
