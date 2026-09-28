# Builder Center Submission — AgentSentry AI

Copy the sections below into your Builder Center project post.

- **Category tag:** `#workplace-efficiency`
- **Lane tag:** `#startups`
- **Live app (Ship Gate):** http://agentsentry-dashboard-273354655941.s3-website-us-east-1.amazonaws.com
- **Repository:** https://github.com/sabari-07/Agentsentry
- **Example real remediation PR:** https://github.com/sabari-07/Agentsentry/pull/1

---

## Title

**AgentSentry AI — the AWS incident agent that ships a reviewable fix and proves it worked**

## Short description (for feeds/search)

When AWS infrastructure breaks, AgentSentry AI detects it, inspects the account read-only, opens a
real GitHub pull request containing the fix, cost delta and rollback plan — then re-checks the live
metric after deploy and records a verified resolution.

---

## The problem

Cloud incidents are expensive and they happen at the worst times. A database starts throttling, a
function starts timing out, error rates climb. An engineer then has to notice the alarm, dig through
metrics, work out the right fix, write it, deploy it, and *hope* it worked.

Most "AI ops" tools stop at the first half of that: they hand you a summary or a runbook. You still
do the work, and nobody ever confirms the fix actually held.

## What AgentSentry AI does

AgentSentry AI closes the whole loop, with two things that make it different:

**1. The pull request is the deliverable, not a chat reply.**
Every remediation arrives as a **merge-ready GitHub PR** containing the Infrastructure-as-Code
change, a `cdk diff`, a **cost-delta table**, and a **rollback plan**. It is reviewable, auditable,
and safe by construction: the agent only ever *proposes*. A human merges.

**2. It proves the fix worked.**
After the change deploys, AgentSentry re-reads the **live CloudWatch metric** and only then records
`RESOLVED_VERIFIED` with the observed value and a timestamp. No claim of success without evidence.

### The live loop (all real, nothing seeded)

1. A write burst exceeds the monitored DynamoDB table's capacity → **real throttling**.
2. A **CloudWatch alarm** fires → **EventBridge** → the incident Lambda.
3. The agent performs **read-only inspection** (`DescribeTable`, `GetMetricStatistics`) and writes a
   diagnosis grounded in what it actually observed — e.g. *"PROVISIONED billing (RCU=1, WCU=1) with
   21 throttled PutItem requests in the last 15 minutes."*
4. It creates a branch, commits a remediation manifest, and **opens a real GitHub PR** proposing the
   correct fix (switch to on-demand billing), with cost delta and rollback.
5. The **verification loop** re-checks the metric (now `0.0`) and marks the incident
   **RESOLVED_VERIFIED**.

The dashboard shows this as an incident moving **Active → Open PR → Verified Resolution**, with a
per-incident **read-only audit trail** proving every agent call was `Describe*` / `Get*` / `List*`.

## Why this is safe

- **Read-only by construction** — the agent inspects; it never mutates infrastructure.
- **Human-in-the-loop** — merging is always a human action.
- **Auditable** — every API call the agent made is recorded and surfaced in the UI (and visible in
  CloudTrail Event history).
- **Reversible** — every PR carries a rollback plan.

### Why the reasoning is deterministic, not an LLM

I made a deliberate choice not to have a language model decide infrastructure changes. The
remediation decision is computed from measured facts (billing mode, provisioned capacity, observed
throttle counts), and the supporting guidance is retrieved from **official AWS documentation at
runtime** via the AWS MCP Server, with the sources cited in the pull request.

Wrong infrastructure advice costs money or causes outages. Deterministic logic is reproducible and
reviewable: the same observed state always produces the same recommendation, every number in the PR
is read from the live account, and every claim links to either a recorded read-only API call or an
AWS documentation URL. It also means the system has no inference cost, which keeps it genuinely
100% AWS Free Tier.

The AI leverage in this project is in **how it was built**: the coding agent (Kiro, connected to AWS
through the Agent Toolkit) designed, implemented and debugged the system against the live account,
and the runtime uses that same Agent Toolkit to ground its recommendations in current AWS docs.

## Architecture

- **Frontend:** React + Vite dashboard, hosted on **Amazon S3** static website hosting.
- **API:** FastAPI on **AWS Lambda** (via Mangum) behind an **HTTP API Gateway**.
- **Data:** **Amazon DynamoDB** (incident store, on-demand billing).
- **Detection:** **CloudWatch** alarm → **EventBridge** rule → incident Lambda.
- **Verification:** a dedicated Lambda that re-reads the live metric post-deploy.
- **GitOps:** GitHub REST API (branch → commit → PR); a GitHub Actions workflow can invoke
  verification after a merge.
- **Infrastructure as Code:** **AWS CDK (Python)** — everything above is deployed from `infra/`.

Runs entirely within the **AWS Free Tier** (on-demand DynamoDB, Lambda, HTTP API, S3 static
hosting, and CloudTrail Event history — no trail, no data events).

## How the coding agent helped me ship

I built this with **Kiro** connected to my AWS account through the **Agent Toolkit for AWS (AWS MCP
Server)**, and that connection did real work rather than just autocomplete:

- **Live account inspection while building.** With the AWS MCP Server connected, the agent could
  query my real account (list DynamoDB tables, read stack outputs, inspect metrics) instead of me
  switching to the console to check every assumption.
- **It debugged real deployment failures.** Three genuine problems were found and fixed by reading
  actual CloudWatch logs and AWS errors, not by guessing:
  - `Runtime.ImportModuleError: No module named 'mangum'` — the Lambda asset shipped source without
    dependencies. Fixed by bundling `pip install` into the CDK asset.
  - `No module named 'pydantic_core._pydantic_core'` — Windows wheels had been installed for a Linux
    runtime. Fixed by pulling `manylinux2014_x86_64` wheels at bundle time.
  - `AccessDenied: cloudwatch:GetMetricStatistics` — the API Lambda ran the verification endpoint
    without the matching IAM policy. Fixed by granting the read-only CloudWatch policy.
  - A CDK synth error (`TooManyMetricsInMathExpression`) because the DynamoDB all-operations
    throttling metric exceeds CloudWatch's 10-metric alarm limit. Fixed by alarming on a single
    `ThrottledRequests` metric.
- **Spec-first, then implementation.** I started from a written plan (`project_plan.md`), had the
  agent implement against it, and updated the plan whenever reality differed — for example, the
  frontend moved from Amplify to S3 static hosting after the account hit its Amplify app limit.

## My development process

1. **Plan first.** Wrote the architecture, demo scenario, free-tier budget, and proof strategy
   before coding.
2. **Build the pipeline behind a flag.** `USE_MOCK_DATA=true` let me develop and demo the full UI
   locally with zero AWS calls; flipping it to `false` switches the same code to live AWS.
3. **Deploy with IaC.** One `cdk deploy` provisions tables, Lambdas, API Gateway, the alarm, and the
   EventBridge rule.
4. **Make it genuinely live.** Rather than leave scripted demo data, I added a load generator that
   causes **real** throttling so incidents are self-generated by real AWS events.
5. **Prove it.** Added the verification loop and the read-only audit trail so every claim the
   product makes can be checked.

## What's next

- Application-level remediation (e.g. detecting a DynamoDB 400 KB item-size failure and proposing
  the S3-offload pattern, or pagination for oversized reads).
- CloudFront in front of S3 for HTTPS.
- Secrets Manager for the GitHub token, and OIDC for the deploy role.

---

## Attribution / honesty notes

- The dashboard is served over HTTP via S3 static website hosting (AWS Amplify was the original
  plan; that account had reached its Amplify app limit).
- The GitHub Actions merge → verify workflow is present but set to manual trigger; the verification
  loop itself runs live and was exercised end to end via the API.
