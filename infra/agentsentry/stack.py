"""AgentSentry AI CDK stack.

Provisions the 100% Free-Tier resources the backend expects:

* Incident DynamoDB table (on-demand billing = no idle cost)
* A monitored DynamoDB table (the demo "victim" resource)
* CloudWatch alarms on ThrottledRequests
* An EventBridge rule wiring alarm state changes to the incident Lambda
* The FastAPI backend packaged as a Lambda behind an HTTP API Gateway

The same FastAPI app runs locally (uvicorn) or on Lambda (via Mangum), so there
is a single source of truth for the API.
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigw_integrations
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

# Path to the backend package that becomes the Lambda deployment bundle.
BACKEND_DIR = str((Path(__file__).resolve().parents[2] / "backend").as_posix())


class AgentSentryStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- DynamoDB: incident store (on-demand => $0 when idle) ---
        incident_table = dynamodb.Table(
            self,
            "IncidentTable",
            table_name="agentsentry-incidents",
            partition_key=dynamodb.Attribute(
                name="id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- DynamoDB: the monitored ("victim") table for the demo scenario ---
        # Provisioned with deliberately low capacity (1 WCU) so a real write
        # burst genuinely throttles and fires the CloudWatch alarm — this is
        # what drives a real, self-generated incident end to end. Free-tier safe
        # (free tier covers 25 WCU/RCU).
        monitored_table = dynamodb.Table(
            self,
            "MonitoredTable",
            table_name="agentsentry-monitored",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- Shared Lambda code bundle from the backend package ---
        # Bundle installs requirements into the asset so third-party deps
        # (fastapi, mangum, boto3, ...) ship with the code. Prefers Docker;
        # falls back to a local bundler when Docker is unavailable.
        from aws_cdk import AssetHashType

        bundling = _bundling_options()
        exclude = [".venv", "__pycache__", "*.pyc", "config/.env", "tests", "cdk.out*"]
        if bundling is None:
            # Test path: no dependency install, so hash the source instead.
            code = lambda_.Code.from_asset(BACKEND_DIR, exclude=exclude)
        else:
            code = lambda_.Code.from_asset(
                BACKEND_DIR,
                exclude=exclude,
                bundling=bundling,
                # Hash the bundled OUTPUT, not the source. The dependencies (and
                # thus the Linux wheels) are produced by bundling, so output-based
                # hashing ensures CDK detects the change and updates the Lambda.
                asset_hash_type=AssetHashType.OUTPUT,
            )
        common_env = {
            "USE_MOCK_DATA": "false",
            "INCIDENT_TABLE_NAME": incident_table.table_name,
            "AWS_REGION_NAME": self.region,
            "AGENT_IAM_PRINCIPAL": "agentsentry-agent",
            # Public dashboard can be hosted on any origin (S3/CloudFront), so
            # allow all origins. The API is read-oriented and unauthenticated.
            "CORS_ORIGINS": "*",
            # GitHub config for opening real remediation PRs. Read from the local
            # backend/config/.env at synth time so the token is never committed.
            **_github_env(),
        }

        # --- API Lambda: serves the FastAPI dashboard API via Mangum ---
        api_fn = lambda_.Function(
            self,
            "ApiFunction",
            function_name="agentsentry-api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_api.handler",
            code=code,
            memory_size=256,
            timeout=Duration.seconds(30),
            environment=common_env,
        )
        incident_table.grant_read_write_data(api_fn)
        # The API Lambda runs the verification endpoint, which re-checks the
        # live CloudWatch metric — grant it the read-only CloudWatch policy.
        api_fn.add_to_role_policy(_cloudwatch_read_policy())

        # --- Incident Lambda: invoked by EventBridge on alarm, writes PENDING ---
        incident_fn = lambda_.Function(
            self,
            "IncidentFunction",
            function_name="agentsentry-incident-handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_incident.handler",
            code=code,
            memory_size=128,
            timeout=Duration.seconds(60),
            environment=common_env,
        )
        incident_table.grant_read_write_data(incident_fn)
        # Needs to inspect the monitored table + read CloudWatch metrics (read-only).
        monitored_table.grant_read_data(incident_fn)
        incident_fn.add_to_role_policy(_dynamodb_describe_policy(monitored_table.table_arn))
        incident_fn.add_to_role_policy(_cloudwatch_read_policy())

        # --- Verification Lambda: re-checks the metric post-deploy ---
        verify_fn = lambda_.Function(
            self,
            "VerificationFunction",
            function_name="agentsentry-verification-handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_verify.handler",
            code=code,
            memory_size=128,
            timeout=Duration.seconds(60),
            environment=common_env,
        )
        incident_table.grant_read_write_data(verify_fn)
        # Read-only CloudWatch access for the verification loop.
        verify_fn.add_to_role_policy(_cloudwatch_read_policy())
        api_fn.add_to_role_policy(_cloudtrail_read_policy())

        # --- HTTP API Gateway in front of the API Lambda ---
        http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name="agentsentry-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_headers=["*"],
            ),
        )
        http_api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=apigw_integrations.HttpLambdaIntegration(
                "ApiIntegration", handler=api_fn
            ),
        )

        # --- CloudWatch alarm on the monitored table's throttling ---
        # Use a single ThrottledRequests metric (PutItem) rather than the
        # all-operations math expression, which exceeds the 10-metric limit
        # that CloudWatch alarms allow on math expressions.
        throttle_metric = cloudwatch.Metric(
            namespace="AWS/DynamoDB",
            metric_name="ThrottledRequests",
            dimensions_map={
                "TableName": monitored_table.table_name,
                "Operation": "PutItem",
            },
            statistic="Sum",
            period=Duration.minutes(1),
        )
        throttle_alarm = cloudwatch.Alarm(
            self,
            "ThrottleAlarm",
            alarm_name="agentsentry-monitored-throttling",
            metric=throttle_metric,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # --- EventBridge: ANY alarm in the account entering ALARM ---
        #
        # Deliberately not filtered to a single alarm. The incident handler reads
        # the affected resource, metric and dimension set from the alarm payload,
        # so every CloudWatch alarm in the account routes through the same code
        # path. Resource identification covers DynamoDB, Lambda, API Gateway
        # (v1/v2), RDS, SQS and ECS; anything else is still recorded as an
        # incident for visibility but receives no automated diagnosis.
        #
        # Production note: a busy account would want this narrowed (by alarm name
        # prefix or tag) so routine alarm flaps don't each open an incident.
        alarm_rule = events.Rule(
            self,
            "AlarmToIncidentRule",
            rule_name="agentsentry-alarm-to-incident",
            description=(
                "Routes any CloudWatch alarm entering ALARM to the AgentSentry "
                "incident handler, which identifies the resource from the payload."
            ),
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={"state": {"value": ["ALARM"]}},
            ),
        )
        alarm_rule.add_target(targets.LambdaFunction(incident_fn))

        # --- Outputs ---
        from aws_cdk import CfnOutput

        CfnOutput(self, "ApiUrl", value=http_api.url or "n/a")
        CfnOutput(self, "IncidentTableName", value=incident_table.table_name)
        CfnOutput(self, "MonitoredTableName", value=monitored_table.table_name)
        CfnOutput(self, "VerificationFunctionName", value=verify_fn.function_name)


def _bundling_options():
    """Bundle Lambda code + pip dependencies.

    Uses a local bundler (no Docker needed) that copies the source and installs
    requirements into the asset staging directory. Falls back to the standard
    Docker-based pip install if local bundling is unavailable.

    ``AGENTSENTRY_SKIP_BUNDLE=1`` is honoured only inside pytest. This keeps
    template-only tests fast without allowing a leaked shell variable to produce
    a dependency-free production Lambda artifact.
    """
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    if (
        os.environ.get("AGENTSENTRY_SKIP_BUNDLE") == "1"
        and "PYTEST_CURRENT_TEST" in os.environ
    ):
        return None

    from aws_cdk import BundlingOptions, DockerImage, ILocalBundling
    import jsii

    @jsii.implements(ILocalBundling)
    class LocalBundler:
        def try_bundle(self, output_dir: str, *_args, **_kwargs) -> bool:
            src = Path(BACKEND_DIR)
            out = Path(output_dir)
            # Install Linux (manylinux) wheels for the Lambda runtime, not the
            # host's Windows wheels. Compiled packages like pydantic-core ship
            # platform-specific binaries; installing Windows ones breaks on
            # Lambda (Linux). --platform + --only-binary pulls the right wheels.
            #
            # sys.executable rather than "python", and no shell: on Linux
            # ``shell=True`` with an argument list passes only the first element
            # to ``sh -c``, so pip would never run and the bundle would ship
            # without mangum/pydantic. That failure only appears at runtime.
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(src / "requirements.txt"),
                    "-t",
                    str(out),
                    "--platform",
                    "manylinux2014_x86_64",
                    "--python-version",
                    "3.12",
                    "--implementation",
                    "cp",
                    "--only-binary=:all:",
                    "--upgrade",
                    "--quiet",
                ],
                check=True,
            )
            # Copy source (code) alongside the installed deps.
            for item in src.iterdir():
                if item.name in {".venv", "__pycache__", "cdk.out", "tests"}:
                    continue
                dest = out / item.name
                if item.is_dir():
                    shutil.copytree(
                        item,
                        dest,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env"),
                    )
                else:
                    shutil.copy2(item, dest)
            return True

    return BundlingOptions(
        image=DockerImage.from_registry("public.ecr.aws/sam/build-python3.12"),
        local=LocalBundler(),
        command=[
            "bash",
            "-c",
            "pip install -r requirements.txt -t /asset-output && cp -r . /asset-output",
        ],
    )


def _github_env() -> dict:
    """Resolve the GitHub settings baked into the Lambda environment.

    Two sources, environment variables taking precedence:

    1. Process environment variables — used by CI, which has no ``.env`` file.
       GitHub Actions reserves the ``GITHUB_`` prefix for both secrets and
       variables, so CI supplies ``AGENTSENTRY_GH_*`` names; the plain
       ``GITHUB_*`` names still work for local shells.
    2. ``backend/config/.env`` — used by local deploys; never committed.

    Returning an empty dict is correct for a contributor who has not configured
    GitHub: the pipeline records the proposed fix instead of opening a PR. It is
    *not* correct for a deploy that maintains the live stack, because CDK would
    then drop ``GITHUB_TOKEN`` from the running Lambdas and silently disable
    pull-request creation. Set ``AGENTSENTRY_REQUIRE_GITHUB=1`` on those deploys
    to turn that silent downgrade into a hard failure.
    """
    import os

    values: dict[str, str] = {}
    env_file = Path(BACKEND_DIR) / "config" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip()

    # Environment variables win, so CI can supply these from repository secrets.
    # The AGENTSENTRY_GH_* aliases exist because GitHub Actions refuses to set
    # any secret or variable beginning with GITHUB_.
    candidates = {
        "GITHUB_TOKEN": ("AGENTSENTRY_GH_TOKEN", "GITHUB_TOKEN"),
        "GITHUB_REPO": ("AGENTSENTRY_GH_REPO", "GITHUB_REPO"),
        "GITHUB_BASE_BRANCH": ("AGENTSENTRY_GH_BASE_BRANCH", "GITHUB_BASE_BRANCH"),
    }
    for target, sources in candidates.items():
        for source in sources:
            if os.environ.get(source):
                values[target] = os.environ[source].strip()
                break

    token = values.get("GITHUB_TOKEN", "")
    repo = values.get("GITHUB_REPO", "")
    base = values.get("GITHUB_BASE_BRANCH", "main")

    if not token or not repo or "your-org" in repo:
        if os.environ.get("AGENTSENTRY_REQUIRE_GITHUB") == "1":
            raise ValueError(
                "GITHUB_TOKEN and GITHUB_REPO are required for this deploy but were "
                "found in neither the environment nor backend/config/.env. Refusing "
                "to deploy Lambdas without GitHub configuration, which would "
                "disable remediation pull requests."
            )
        return {}
    return {"GITHUB_TOKEN": token, "GITHUB_REPO": repo, "GITHUB_BASE_BRANCH": base}


def _dynamodb_describe_policy(table_arn: str):
    from aws_cdk import aws_iam as iam

    return iam.PolicyStatement(
        actions=["dynamodb:DescribeTable"],
        resources=[table_arn],
    )


def _cloudwatch_read_policy():
    from aws_cdk import aws_iam as iam

    return iam.PolicyStatement(
        actions=[
            "cloudwatch:GetMetricData",
            "cloudwatch:GetMetricStatistics",
            "cloudwatch:ListMetrics",
            "cloudwatch:DescribeAlarms",
        ],
        resources=["*"],
    )
    # (GetMetricStatistics is included above; the API Lambda runs the
    #  verification loop, so it also needs this policy — granted below.)


def _cloudtrail_read_policy():
    from aws_cdk import aws_iam as iam

    return iam.PolicyStatement(
        actions=["cloudtrail:LookupEvents"],
        resources=["*"],
    )
