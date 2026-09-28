"""LLM reasoning over the evidence gathered from a live incident.

Design contract, and the reason this file is small and boring:

* The model **analyses**. It receives only facts already measured from the
  account (alarm payload, resource configuration, metric values, AWS
  documentation) and returns a *structured decision*.
* The model never writes code, never names a file, and never chooses a
  resource. It selects an ``action`` from a fixed allowlist, and that action is
  executed by the existing guarded source transformer.
* Deterministic validation sits between the two. A decision is rejected unless
  the action is recognised and ``target_resource`` matches the resource the
  CloudWatch alarm actually named. This is what stops a confident model from
  retargeting a remediation at the wrong table.
* Every failure path returns ``None`` so the caller falls back to the
  deterministic diagnosis. Losing the narrative is acceptable; losing the
  incident is not.

Credentials are deliberately separate from the application's own AWS identity:
inference runs in whichever account owns the model entitlement, read at runtime
from Secrets Manager. Secret values are never logged.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from config import Settings

logger = logging.getLogger("agentsentry.reasoning")

# Actions the agent is permitted to propose. Anything outside this set means
# "explain it, but do not open a pull request".
ACTION_SET_ON_DEMAND = "SET_BILLING_MODE_ON_DEMAND"
ACTION_NO_SAFE_FIX = "NO_SAFE_AUTOMATED_FIX"
_ALLOWED_ACTIONS = (ACTION_SET_ON_DEMAND, ACTION_NO_SAFE_FIX)


class ReasoningDecision(BaseModel):
    """A validated, constrained decision returned by the model."""

    root_cause: str = Field(min_length=1)
    action: Literal["SET_BILLING_MODE_ON_DEMAND", "NO_SAFE_AUTOMATED_FIX"]
    target_resource: str = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
    reasoning: str = Field(min_length=1)
    impact: str = ""
    rejected_alternatives: list[str] = Field(default_factory=list)

    @property
    def proposes_change(self) -> bool:
        """True only when the model both proposes a fix and is confident in it."""
        return self.action == ACTION_SET_ON_DEMAND and self.confidence in ("high", "medium")


_SYSTEM_PROMPT = """You are an AWS site-reliability engineer reviewing a live \
CloudWatch incident. You are given only evidence that has already been measured \
from the account. Do not speculate beyond it and do not invent numbers.

Decide the root cause, then choose exactly one action:

- "SET_BILLING_MODE_ON_DEMAND": the resource is a DynamoDB table whose fixed \
provisioned capacity is the cause of the throttling, and switching it to \
on-demand billing is the correct durable fix.
- "NO_SAFE_AUTOMATED_FIX": anything else. Use this when the cause is a hot \
partition, an access-pattern problem, a downstream dependency, an \
already-on-demand table, or when the evidence is insufficient. Explaining the \
problem accurately is more valuable than forcing a fix.

Reply with a single JSON object and nothing else:

{
  "root_cause": "one or two sentences naming the specific cause",
  "action": "SET_BILLING_MODE_ON_DEMAND" | "NO_SAFE_AUTOMATED_FIX",
  "target_resource": "the exact resource identifier you were given",
  "confidence": "high" | "medium" | "low",
  "reasoning": "why this action follows from the measured evidence, citing the numbers",
  "impact": "what this failure does to users or data, in markdown bullets",
  "rejected_alternatives": ["option and the specific reason it is worse"]
}"""


class ReasoningService:
    """Optional LLM analysis layer. Absent or failing, the pipeline continues."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._config: dict | None = None
        self._attempted = False

    # ------------------------------------------------------------------ #
    # Credential loading
    # ------------------------------------------------------------------ #
    def _load_config(self) -> dict | None:
        """Fetch inference credentials from Secrets Manager, once per container.

        Returns None when the secret is missing or malformed, which disables
        reasoning rather than breaking remediation.
        """
        if self._attempted:
            return self._config
        self._attempted = True

        secret_name = self._settings.llm_secret_name
        if not secret_name:
            logger.info("No LLM secret configured; using deterministic diagnosis.")
            return None

        try:
            import boto3

            # Read the credentials with the application's own identity.
            session = boto3.Session(
                aws_access_key_id=self._settings.aws_access_key_id,
                aws_secret_access_key=self._settings.aws_secret_access_key,
                aws_session_token=self._settings.aws_session_token,
                region_name=self._settings.region,
            )
            # A leading "/" means an SSM Parameter Store SecureString, which is
            # free at the standard tier. Anything else is a Secrets Manager
            # secret id, which is billed per secret per month.
            if secret_name.startswith("/"):
                raw = session.client("ssm").get_parameter(
                    Name=secret_name, WithDecryption=True
                )
                document = raw["Parameter"]["Value"]
            else:
                document = session.client("secretsmanager").get_secret_value(
                    SecretId=secret_name
                )["SecretString"]
            payload = json.loads(document)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not read LLM credentials from %s; reasoning disabled.", secret_name
            )
            return None

        # Accept a few common key spellings so the secret is easy to author.
        def pick(*names: str) -> str:
            for name in names:
                value = payload.get(name)
                if value:
                    return str(value).strip()
            return ""

        config = {
            "access_key_id": pick("aws_access_key_id", "access_key_id", "AWS_ACCESS_KEY_ID"),
            "secret_access_key": pick(
                "aws_secret_access_key", "secret_access_key", "AWS_SECRET_ACCESS_KEY"
            ),
            "session_token": pick("aws_session_token", "session_token", "AWS_SESSION_TOKEN"),
            "region": pick("region", "aws_region", "AWS_REGION", "region_name"),
            "model_id": pick("model_id", "model", "modelId", "MODEL_ID"),
        }

        missing = [k for k in ("access_key_id", "secret_access_key", "region", "model_id")
                   if not config[k]]
        if missing:
            # Names only — never the values.
            logger.error("LLM secret %s is missing keys: %s", secret_name, ", ".join(missing))
            return None

        logger.info(
            "LLM reasoning enabled: model=%s region=%s", config["model_id"], config["region"]
        )
        self._config = config
        return config

    @property
    def available(self) -> bool:
        return self._load_config() is not None

    # ------------------------------------------------------------------ #
    # Analysis
    # ------------------------------------------------------------------ #
    def analyze(
        self,
        *,
        resource_id: str,
        resource_type: str,
        metric_name: str,
        namespace: str,
        threshold: float,
        facts: dict,
        docs: list[dict] | None = None,
    ) -> ReasoningDecision | None:
        """Analyse measured evidence and return a validated decision, or None."""
        config = self._load_config()
        if config is None:
            return None

        evidence = self._format_evidence(
            resource_id=resource_id,
            resource_type=resource_type,
            metric_name=metric_name,
            namespace=namespace,
            threshold=threshold,
            facts=facts,
            docs=docs or [],
        )

        try:
            import boto3
            from botocore.config import Config

            session = boto3.Session(
                aws_access_key_id=config["access_key_id"],
                aws_secret_access_key=config["secret_access_key"],
                aws_session_token=config["session_token"] or None,
                region_name=config["region"],
            )
            client = session.client(
                "bedrock-runtime",
                config=Config(read_timeout=25, connect_timeout=5, retries={"max_attempts": 1}),
            )
            response = client.converse(
                modelId=config["model_id"],
                system=[{"text": _SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": evidence}]}],
                inferenceConfig={"maxTokens": 1200, "temperature": 0.0},
            )
            text = response["output"]["message"]["content"][0]["text"]
            usage = response.get("usage", {})
            logger.info(
                "reasoning tokens in=%s out=%s",
                usage.get("inputTokens"), usage.get("outputTokens"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("LLM reasoning call failed; falling back to deterministic path.")
            return None

        return self._validate(text, expected_resource=resource_id)

    # ------------------------------------------------------------------ #
    # Prompt + validation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _format_evidence(
        *,
        resource_id: str,
        resource_type: str,
        metric_name: str,
        namespace: str,
        threshold: float,
        facts: dict,
        docs: list[dict],
    ) -> str:
        lines = [
            "Evidence measured from the live AWS account:",
            "",
            f"- Resource: {resource_id}",
            f"- Resource type: {resource_type}",
            f"- Breaching metric: {namespace}/{metric_name}",
            f"- Alarm threshold: {threshold:g}",
        ]
        if facts.get("billing_mode"):
            lines.append(f"- Billing mode (from DescribeTable): {facts['billing_mode']}")
        if facts.get("wcu") is not None:
            lines.append(f"- Provisioned write capacity: {facts['wcu']} WCU")
        if facts.get("rcu") is not None:
            lines.append(f"- Provisioned read capacity: {facts['rcu']} RCU")
        if facts.get("throttled_15m") is not None:
            lines.append(
                f"- Throttled PutItem requests, last 15 minutes "
                f"(GetMetricStatistics, Sum): {facts['throttled_15m']:g}"
            )
        if facts.get("item_count") is not None:
            lines.append(f"- Approximate item count: {facts['item_count']}")

        if docs:
            lines += ["", "Relevant AWS documentation retrieved at runtime:"]
            for doc in docs:
                title = doc.get("title", "AWS documentation")
                excerpt = (doc.get("excerpt") or "")[:400]
                lines.append(f"- {title}: {excerpt}")

        lines += ["", f"The resource identifier you must echo back is: {resource_id}"]
        return "\n".join(lines)

    @staticmethod
    def _extract_json(text: str) -> str:
        """Pull the JSON object out of a reply, tolerating code fences."""
        cleaned = text.strip()
        if "```" in cleaned:
            parts = cleaned.split("```")
            for part in parts:
                candidate = part.removeprefix("json").strip()
                if candidate.startswith("{"):
                    cleaned = candidate
                    break
        start, end = cleaned.find("{"), cleaned.rfind("}")
        return cleaned[start : end + 1] if start >= 0 and end > start else cleaned

    @classmethod
    def _validate(cls, text: str, *, expected_resource: str) -> ReasoningDecision | None:
        """Parse and police the model's reply. Rejection is a normal outcome."""
        try:
            decision = ReasoningDecision.model_validate_json(cls._extract_json(text))
        except (ValidationError, ValueError):
            logger.warning("Model reply was not a valid decision; ignoring it.")
            return None

        if decision.action not in _ALLOWED_ACTIONS:  # pragma: no cover - Literal guards this
            logger.error("Rejected unknown action %r.", decision.action)
            return None

        # The model must not be able to redirect a fix at a different resource.
        if decision.target_resource.strip() != expected_resource:
            logger.error(
                "Rejected decision: target_resource %r does not match the alarmed "
                "resource %r.",
                decision.target_resource, expected_resource,
            )
            return None

        logger.info(
            "reasoning decision: action=%s confidence=%s", decision.action, decision.confidence
        )
        return decision
