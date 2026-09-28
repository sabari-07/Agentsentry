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
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

# Path to the backend package that becomes the Lambda deployment bundle.
BACKEND_DIR = str((Path(__file__).resolve().parents[2] / "backend").as_posix())

# Where the LLM inference credentials, region and model id are stored.
# Deliberately separate from the application's own AWS identity so the model
# entitlement can live in a different account.
#
# An SSM Parameter Store SecureString is used rather than a Secrets Manager
# secret: standard-tier parameters and the AWS managed KMS key are free, whereas
# Secrets Manager bills per secret per month. The leading "/" is what tells the
# runtime which store to read.
LLM_SECRET_NAME = "/agentsentry/llm"

# Bucket holding the built dashboard. Served over the API's HTTPS endpoint
# because the S3 website endpoint is HTTP-only and CloudFront is unavailable
# until the account is verified.
DASHBOARD_BUCKET = "agentsentry-dashboard-273354655941"

# Date the stored inference credentials are deleted automatically. Hackathon
# winners are announced the week of 19 Oct 2026 and the rules allow AWS to extend
# that while verifying eligibility, so this leaves a deliberate buffer. After
# this date the reasoning layer disables itself and the deterministic diagnosis
# takes over.
LLM_CREDENTIAL_EXPIRY = "2026-10-31"


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
            # Secrets Manager secret holding inference-only credentials, region
            # and model id. Empty/absent simply disables the reasoning layer.
            "LLM_SECRET_NAME": LLM_SECRET_NAME,
            # Lets the API Lambda serve the dashboard from S3 over HTTPS.
            "DASHBOARD_BUCKET": DASHBOARD_BUCKET,
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
        # Read-only access to the dashboard bucket so the API can serve the
        # SPA over HTTPS. Scoped to this one bucket's objects.
        api_fn.add_to_role_policy(_dashboard_read_policy())

        # --- Incident Lambda: invoked by EventBridge on alarm, writes PENDING ---
        incident_fn = lambda_.Function(
            self,
            "IncidentFunction",
            function_name="agentsentry-incident-handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_incident.handler",
            code=code,
            # Sized for the reasoning path: a measured run used 123 MB of 128 MB
            # and 37 s of 60 s once the Bedrock client was loaded, which left no
            # headroom at all. More memory also raises the CPU share, so the
            # model call completes sooner.
            memory_size=512,
            timeout=Duration.seconds(120),
            environment=common_env,
        )
        incident_table.grant_read_write_data(incident_fn)
        # Needs to inspect the monitored table + read CloudWatch metrics (read-only).
        monitored_table.grant_read_data(incident_fn)
        incident_fn.add_to_role_policy(_dynamodb_describe_policy(monitored_table.table_arn))
        # Read the inference credentials only. Scoped to this one name so the
        # incident Lambda cannot enumerate or read anything else.
        for statement in _llm_secret_read_policies(self.region, self.account):
            incident_fn.add_to_role_policy(statement)
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
        api_integration = apigw_integrations.HttpLambdaIntegration(
            "ApiIntegration", handler=api_fn
        )
        # "/{proxy+}" does not match the root, so route "/" explicitly — that is
        # where the dashboard is served.
        http_api.add_routes(
            path="/", methods=[apigwv2.HttpMethod.ANY], integration=api_integration
        )
        http_api.add_routes(
            path="/{proxy+}", methods=[apigwv2.HttpMethod.ANY], integration=api_integration
        )

        # --- Scheduled credential expiry -------------------------------- #
        # Inference credentials are only needed while the project is judged.
        # This deletes them on LLM_CREDENTIAL_EXPIRY so they are not left in the
        # account indefinitely; the reasoning layer then falls back to the
        # deterministic path on its own.
        expiry_fn = lambda_.Function(
            self,
            "CredentialExpiryFunction",
            function_name="agentsentry-credential-expiry",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_credential_expiry.handler",
            code=code,
            memory_size=128,
            timeout=Duration.seconds(30),
            environment={
                "LLM_SECRET_NAME": LLM_SECRET_NAME,
                "LLM_CREDENTIAL_EXPIRY": LLM_CREDENTIAL_EXPIRY,
            },
        )
        for statement in _llm_credential_delete_policies(self.region, self.account):
            expiry_fn.add_to_role_policy(statement)

        # Daily rather than a single one-off schedule: the handler compares the
        # date itself, so this survives redeploys and is safely idempotent.
        events.Rule(
            self,
            "CredentialExpiryRule",
            rule_name="agentsentry-credential-expiry",
            description=(
                "Daily check that deletes the stored LLM inference credentials "
                f"on or after {LLM_CREDENTIAL_EXPIRY}."
            ),
            schedule=events.Schedule.cron(minute="0", hour="3"),
            targets=[targets.LambdaFunction(expiry_fn)],
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

        # --- CloudFront: HTTPS for the dashboard ------------------------- #
        # Disabled by default. This account is not yet verified for CloudFront:
        # creating a distribution returns
        #   "Your account must be verified before you can add new CloudFront
        #    resources. To verify your account, please contact AWS Support."
        # which is a support-ticket gate, not a permissions problem. Leaving the
        # construct behind a flag keeps every other deploy working while making
        # HTTPS a one-variable change once the account is verified:
        #
        #   AGENTSENTRY_ENABLE_CLOUDFRONT=1 cdk deploy
        #
        # The dashboard bucket is managed outside this stack, so CloudFront
        # points at its S3 *website* endpoint as a plain HTTP custom origin
        # rather than adopting the bucket. That keeps the change additive: the
        # existing S3 URL keeps serving throughout, and CloudFront simply adds
        # TLS at the edge on a *.cloudfront.net domain, no certificate needed.
        #
        # Content is public by design, so leaving the bucket readable is not a
        # confidentiality concern; origin access control would be hygiene rather
        # than protection here.
        if _cloudfront_enabled():
            self._add_dashboard_distribution()

        from aws_cdk import CfnOutput

        CfnOutput(self, "ApiUrl", value=http_api.url or "n/a")
        CfnOutput(self, "IncidentTableName", value=incident_table.table_name)
        CfnOutput(self, "MonitoredTableName", value=monitored_table.table_name)
        CfnOutput(self, "VerificationFunctionName", value=verify_fn.function_name)

    def _add_dashboard_distribution(self) -> None:
        """Front the existing S3 website endpoint with CloudFront for HTTPS."""
        from aws_cdk import CfnOutput

        dashboard_origin = origins.HttpOrigin(
            f"agentsentry-dashboard-{self.account}.s3-website-{self.region}.amazonaws.com",
            # S3 website endpoints only speak HTTP.
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
        )

        # Short TTLs: the JS/CSS filenames are content-hashed, but index.html is
        # not, and a judge must never be served a stale build after a deploy.
        dashboard_cache = cloudfront.CachePolicy(
            self,
            "DashboardCachePolicy",
            cache_policy_name="agentsentry-dashboard-short-ttl",
            comment="Short TTL so a fresh deploy is visible without invalidation.",
            default_ttl=Duration.seconds(60),
            min_ttl=Duration.seconds(0),
            max_ttl=Duration.seconds(300),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )

        distribution = cloudfront.Distribution(
            self,
            "DashboardDistribution",
            comment="AgentSentry dashboard over HTTPS",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=dashboard_origin,
                # Plain HTTP requests are redirected rather than refused, so old
                # links keep working.
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD,
                cache_policy=dashboard_cache,
                compress=True,
            ),
            price_class=cloudfront.PriceClass.PRICE_CLASS_ALL,
        )

        CfnOutput(
            self,
            "DashboardHttpsUrl",
            value=f"https://{distribution.distribution_domain_name}",
            description="HTTPS entry point for the dashboard and the judges' tour.",
        )


def _cloudfront_enabled() -> bool:
    """True when the account is verified for CloudFront and HTTPS is wanted.

    Off by default: an unverified account fails the whole deploy when a
    distribution is created, which would block unrelated changes.
    """
    import os

    return os.environ.get("AGENTSENTRY_ENABLE_CLOUDFRONT") == "1"


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


def _llm_secret_read_policies(region: str, account: str) -> list:
    """Allow reading only the LLM credentials, from either supported store."""
    from aws_cdk import aws_iam as iam

    parameter_name = LLM_SECRET_NAME.lstrip("/")
    statements = [
        iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{region}:{account}:parameter/{parameter_name}"],
        ),
        # SecureString values are decrypted with the AWS managed key for SSM.
        # Scoped so this grant cannot be used against any other service.
        iam.PolicyStatement(
            actions=["kms:Decrypt"],
            resources=["*"],
            conditions={"StringEquals": {"kms:ViaService": f"ssm.{region}.amazonaws.com"}},
        ),
        # Kept so a Secrets Manager id also works without a redeploy.
        iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            # Secrets Manager appends a random 6-character suffix to the ARN.
            resources=[f"arn:aws:secretsmanager:{region}:{account}:secret:{parameter_name}-*"],
        ),
    ]
    return statements


def _llm_credential_delete_policies(region: str, account: str) -> list:
    """Allow deleting only the LLM credentials, from either supported store."""
    from aws_cdk import aws_iam as iam

    parameter_name = LLM_SECRET_NAME.lstrip("/")
    return [
        iam.PolicyStatement(
            actions=["ssm:DeleteParameter"],
            resources=[f"arn:aws:ssm:{region}:{account}:parameter/{parameter_name}"],
        ),
        iam.PolicyStatement(
            actions=["secretsmanager:DeleteSecret"],
            resources=[f"arn:aws:secretsmanager:{region}:{account}:secret:{parameter_name}-*"],
        ),
    ]


def _dashboard_read_policy():
    """Read-only access to the dashboard bucket's objects, nothing else."""
    from aws_cdk import aws_iam as iam

    return iam.PolicyStatement(
        actions=["s3:GetObject"],
        resources=[f"arn:aws:s3:::{DASHBOARD_BUCKET}/*"],
    )


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
