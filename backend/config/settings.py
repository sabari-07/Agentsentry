"""Application settings.

Credentials and configuration are loaded from ``backend/config/.env``.
This module is the single source of truth for configuration; nothing else in
the codebase should read environment variables directly.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the .env that lives alongside this file (backend/config/.env).
CONFIG_DIR = Path(__file__).resolve().parent
ENV_FILE = CONFIG_DIR / ".env"


class Settings(BaseSettings):
    """Strongly-typed application settings, sourced from config/.env."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"

    # --- AWS ---
    # On Lambda, AWS_REGION is reserved and cannot be set as a custom env var,
    # so we also accept AWS_REGION_NAME and fall back to it.
    aws_region: str = "us-east-1"
    aws_region_name: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None

    # --- AWS resources ---
    incident_table_name: str = "agentsentry-incidents"
    agent_iam_principal: str = "agentsentry-agent"

    # --- LLM reasoning (optional) ---
    # Where the inference-only credentials live. Kept separate from the
    # application's own AWS identity so the model entitlement can sit in a
    # different account.
    #
    # A leading "/" selects SSM Parameter Store (SecureString, free at the
    # standard tier); any other value is treated as a Secrets Manager secret id
    # (billed monthly). Expected JSON in either case:
    #   {"aws_access_key_id", "aws_secret_access_key", "region", "model_id"}
    # Empty disables reasoning and the deterministic diagnosis is used.
    llm_secret_name: str = ""

    # --- GitHub ---
    github_token: str | None = None
    github_repo: str = "your-org/agentsentry-ai"
    github_base_branch: str = "main"
    # Optional map of monitored resource -> repository that owns its IaC, so one
    # deployment can raise pull requests against the right repo per resource.
    # Format: "table-a=org/repo-a,function-b=org/repo-b". Falls back to
    # github_repo for anything not listed.
    resource_repo_map: str = ""

    # --- Behaviour ---
    verification_window_minutes: int = 5
    use_mock_data: bool = True

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins as a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def region(self) -> str:
        """Effective AWS region (prefers AWS_REGION_NAME when running on Lambda)."""
        return self.aws_region_name or self.aws_region

    def repo_for_resource(self, resource_id: str) -> str:
        """Repository that owns the IaC for ``resource_id``.

        Uses RESOURCE_REPO_MAP when the resource is listed, otherwise the default
        GITHUB_REPO. This routes the pull request only; each mapped repository
        must use the supported IaC layout and own its deployment integration.
        """
        for pair in self.resource_repo_map.split(","):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            resource, _, repo = pair.partition("=")
            if resource.strip() == resource_id and repo.strip():
                return repo.strip()
        return self.github_repo

    @property
    def has_aws_credentials(self) -> bool:
        """True when explicit AWS keys are present in config."""
        return bool(self.aws_access_key_id and self.aws_secret_access_key)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()
