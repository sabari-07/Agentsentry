#!/usr/bin/env python
"""CDK app entrypoint for AgentSentry AI."""
import os

import aws_cdk as cdk

from agentsentry.stack import AgentSentryStack

app = cdk.App()

AgentSentryStack(
    app,
    "AgentSentryStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="AgentSentry AI - autonomous cloud incident remediation copilot",
)

app.synth()
