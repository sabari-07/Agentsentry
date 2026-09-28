# Builder Center Submission — AgentSentry AI

Copy the sections below into your Builder Center project post.

- **Category tag:** `#workplace-efficiency`
- **Lane tag:** `#startups`
- **Live app (Ship Gate):** http://agentsentry-dashboard-273354655941.s3-website-us-east-1.amazonaws.com
- **Judges' 3-minute tour:** http://agentsentry-dashboard-273354655941.s3-website-us-east-1.amazonaws.com/#judges
- **Repository:** https://github.com/sabari-07/Agentsentry
- **Real remediation PR (agent-authored):** https://github.com/sabari-07/Agentsentry/pull/4
- **Proof the verification is a real measurement:** the run that
  [withheld certification at 116](https://github.com/sabari-07/Agentsentry/pull/5#issuecomment-5864794338)
  and the run that [confirmed recovery at 0](https://github.com/sabari-07/Agentsentry/pull/5#issuecomment-5864880540)

---

## Title

**AgentSentry AI: the fix is a pull request, and the proof is the metric**

## Short description (for feeds/search)

Most AWS tools tell you what broke. AgentSentry detects the incident, opens a real pull request
containing the fix, then re-reads the live CloudWatch metric after the merge and records whether the
fix actually held — including when it didn't.

---

## The one screen that explains the project

A real incident from this AWS account, end to end, with nothing seeded:

| Step | What actually happened | Evidence |
|---|---|---|
| 1. Break | A write burst exceeded the monitored DynamoDB table's 1 WCU. **121 real `PutItem` requests were refused** with `ProvisionedThroughputExceededException`. | CloudWatch `ThrottledRequests` |
| 2. Detect | A CloudWatch alarm fired → EventBridge → incident Lambda. Incident `INC-1790566592` appeared on the dashboard on its own. | Lambda log, 20.7s execution |
| 2b. Identify | It read the resource, metric, statistic and **full dimension set** from the alarm payload — nothing hardcoded. | "Detected from CloudWatch alarm" panel on every card |
| 3. Inspect | The agent called `DescribeTable` and `GetMetricStatistics` — **read-only only** — and recorded every call. | Read-only audit panel |
| 4. Consult | It queried the **AWS MCP Server (Agent Toolkit)** and cited 3 official AWS documentation sources for the fix. | Section 6 of the PR |
| 5. Propose | It creates a branch and commits the actual `infra/agentsentry/stack.py` billing-mode change **together with** its evidence report, then opens a pull request with diagnosis, `cdk diff`, cost delta, alternatives, and rollback. | The next live PR after deploying this upgrade; [PR #4](https://github.com/sabari-07/Agentsentry/pull/4) is a pre-upgrade report-only artifact. |
| 6. Merge + deploy | A human reviews and merges. The deployment pipeline—not the diagnosis agent—applies the merged IaC change. | GitHub Actions / CDK |
| 7. **Prove** | **After deployment**, the verification loop re-reads the live metric and publishes the measured result as a PR comment. | Verification comment on the PR |

No step in that chain is simulated except the initial load burst, which stands in for a traffic
spike. Detection, inspection, diagnosis, the pull request and the verification are all real.

---

## The problem

Cloud incidents are expensive, and they arrive at the worst time. A table starts throttling, a
function starts timing out, error rates climb. Someone then has to notice the alarm, dig through
metrics, work out the correct fix, write it, deploy it — and then simply *hope* it worked.

Tooling helps with the first half and abandons the second. You get a dashboard, a summary, or a
runbook. You still do the work, and **nothing ever confirms the fix held.**

## What AgentSentry AI does differently

**1. The pull request is the deliverable, not a chat reply.**
Every remediation arrives as a merge-ready GitHub PR containing the Infrastructure-as-Code change, a
`cdk diff`, a **cost-delta table**, **alternatives considered with reasons**, a **rollback plan**,
and the **AWS documentation it consulted**. It is reviewable, auditable, and safe by construction:
the agent only proposes. A human merges.

**2. It proves the fix worked — and says so when it didn't.**
After the merged infrastructure code is deployed, AgentSentry re-reads the live CloudWatch metric and records `RESOLVED_VERIFIED`
**only if** the metric has returned below threshold. If it hasn't, the incident is marked `FAILED`
and the PR says so. Success is measured, never assumed.

### The proof that this is a measurement, not a rubber stamp

Two verification runs against the same incident on **PR #5**, each linked to the comment the agent
published:

| Verdict | Observed | What it means |
|---|---|---|
| ❌ [**Withheld**](https://github.com/sabari-07/Agentsentry/pull/5#issuecomment-5864794338) | `ThrottledRequests` = **116** (threshold 1) | Still breaching, so the agent declined to certify the fix and published that number rather than closing the incident. |
| ✅ [**Confirmed**](https://github.com/sabari-07/Agentsentry/pull/5#issuecomment-5864880540) | `ThrottledRequests` = **0** | The metric had genuinely recovered, so the incident became `RESOLVED_VERIFIED`. |

A tool that only reports can never be wrong about an outcome. This one is accountable for the
outcome, so it has to be able to return a negative result — and when it did, it published that
result instead of hiding it.

**On the earlier comments in that thread.** PR #5's first three ✅ comments predate the dimension-set
fix described below. They are false positives from a build whose verification could not fail, and
they are deliberately left in place, because they are the reason the two runs above can be trusted.
The two links point at the specific post-fix comments.

## Measured result (as of Sept 28)

- **7 historical pull requests authored by the agent**, up to **7,004 characters** of structured
  incident report each (diagnosis, evidence, impact, `cdk diff`, AWS docs consulted, alternatives,
  cost, rollback, audit trail). These PRs predate the real-IaC-commit upgrade and change only the
  report file; they are retained transparently. A fresh post-upgrade PR is still required before
  submission to demonstrate the merge-ready `stack.py` change.
- **7 verification comments** posted back onto those PRs with the measured metric value — including
  **one ❌ failure** that refused to confirm a fix while `ThrottledRequests` sat at 116.
- Every incident **self-generated by a real CloudWatch alarm**; largest observed burst **121 refused
  writes** in one window.
- **Read-only inspection only** — `DescribeTable` and `GetMetricStatistics`, recorded per incident and
  shown in the UI. Zero mutating calls.
- **72 automated tests** (67 in `backend/`, 5 infrastructure assertions in `infra/`), including
  regression tests that pin the CloudWatch dimension set, assert the verification can return
  `FAILED`, prove the resource is read from the alarm payload, and assert the EventBridge rule is
  **not** scoped to a single alarm.
- **Cost: $0.00.** The whole system runs inside the AWS Free Tier: DynamoDB at 1 RCU/1 WCU (free
  tier covers 25/25), three small Lambdas, one HTTP API, one CloudWatch alarm (limit 10), S3 static
  hosting, and **CloudTrail Event history only — no trail, no data events**. There is no model
  inference cost because no model is in the runtime path.

## What it deliberately doesn't do

- **It never applies a change.** It opens a pull request. Merging is a human action, always.
- **It never mutates AWS.** Inspection is `Describe*` / `Get*` / `List*` only, and every call is
  recorded and shown in the UI.
- **A language model never decides the fix.** Deterministic rules read the observed state and select
  the remediation; the supporting guidance comes from official AWS documentation retrieved at
  runtime. Wrong infrastructure advice costs money or causes outages, so the same observed state
  always produces the same, reviewable recommendation.
- **It doesn't claim success it hasn't measured.** An unverified incident stays unverified.

## Scope, stated plainly

- **Detection is account-wide.** The EventBridge rule matches **any** CloudWatch alarm entering
  `ALARM`; it is not pinned to a single alarm or resource.
- **Resource identification covers 7 services.** The handler reads the resource, namespace, metric,
  statistic and the metric's full dimension set out of the alarm payload, and maps DynamoDB, Lambda,
  API Gateway (v1 and v2), RDS, SQS and ECS. An unrecognised namespace is still recorded as an
  incident for visibility; it simply receives no automated diagnosis.
- **Remediation rules currently cover DynamoDB throttling.** That is the one failure mode with a
  proven end-to-end fix. The rest are detection-only today.
- **It only sees what you alarm on.** There is no auto-discovery of unmonitored resources, and I am
  not claiming any.
- **Pull requests can route per resource.** `RESOURCE_REPO_MAP` chooses the destination repository,
  but the current concrete transformer expects `infra/agentsentry/stack.py`. A mapped repository also
  needs that supported layout and its own deployment/verification workflow; routing alone is not an
  end-to-end multi-project claim.
- **Production caveat:** a busy account would want the rule narrowed by alarm name prefix or tag so
  routine alarm flaps don't each open an incident.

## AWS architecture

- **Detect:** any CloudWatch alarm entering `ALARM` → EventBridge rule → `agentsentry-incident-handler`
  Lambda, which identifies the affected resource from the alarm payload rather than a hardcoded name.
- **Inspect:** boto3 read-only calls (`DescribeTable`, `GetMetricStatistics`), each recorded as an audit entry.
- **Ground:** the Lambda calls the **AWS MCP Server** (`https://aws-mcp.us-east-1.api.aws/mcp`) with
  SigV4-signed JSON-RPC and invokes `aws___search_documentation`, citing the sources in the PR.
- **Propose:** GitHub Git Data API — create one atomic commit containing the actual guarded IaC edit
  (`infra/agentsentry/stack.py`) and its evidence report, then open the PR.
- **Deploy + prove:** after human merge, GitHub Actions deploys with CDK when an AWS deploy role is
  configured and only then calls `agentsentry-verification-handler`. For manual deployments, the
  same workflow is dispatched manually afterwards. The Lambda re-reads and comments the metric; it
  never verifies merely because a PR was merged.
- **Store:** DynamoDB (on-demand) holds incidents, PR links and verification results.
- **Serve:** FastAPI on Lambda behind an HTTP API Gateway; React dashboard on S3 static hosting.
- **Infrastructure as Code:** the entire stack is AWS CDK (Python) in `infra/`.

## How the coding agent helped me ship

I built this with **Kiro connected to my AWS account through the Agent Toolkit for AWS (AWS MCP
Server)**. That connection did real work, not autocomplete. Four production failures were found and
fixed by reading actual AWS errors and CloudWatch logs:

1. `Runtime.ImportModuleError: No module named 'mangum'` — the Lambda asset shipped source without
   dependencies. Fixed by bundling `pip install` into the CDK asset at synth time.
2. `No module named 'pydantic_core._pydantic_core'` — Windows wheels had been installed for a Linux
   runtime. Fixed by pulling `manylinux2014_x86_64` wheels during bundling.
3. CDK reported "no changes" while the Lambda stayed broken — the asset hash was computed from
   source, not from the bundled output. Fixed with `AssetHashType.OUTPUT`.
4. `AccessDenied: cloudwatch:GetMetricStatistics` — the API Lambda runs the verification endpoint but
   lacked the matching IAM policy. Found in the Lambda's own logs.

A fifth came from CDK synth: `TooManyMetricsInMathExpression`, because DynamoDB's all-operations
throttling metric exceeds CloudWatch's 10-metric limit for alarms on math expressions. Fixed by
alarming on a single `ThrottledRequests` metric.

### The bug that mattered most

While building the demo I tried to make the verification **fail on purpose**, to check that it
actually could. It reported healthy anyway. That turned out to be a silent false positive in the
verification loop itself, the one component whose entire job is to be trustworthy:

- The alarm watched `ThrottledRequests` with dimensions `{TableName, Operation=PutItem}`, but the
  verification queried only `{TableName}`. A CloudWatch metric is identified by its **complete**
  dimension set, so the partial query matched nothing, returned zero datapoints, and was interpreted
  as "recovered". `list_metrics` confirmed the only published combination includes `Operation`.
- The same query also used `Maximum`. DynamoDB emits each throttle as a separate event of value 1, so
  `Maximum` is always 1 whenever any throttling occurs and says nothing about volume. `Sum` is the
  real count (105 refused writes in the window I measured).

Both are fixed, with the reasoning written into the code so the trap is documented rather than just
patched. The lesson is uncomfortable and worth stating plainly: a verification step that cannot fail
is indistinguishable from no verification at all. Being able to withhold certification is what makes
the confirmations mean anything.

The same Agent Toolkit then became a **runtime dependency**: the deployed Lambda queries it for AWS
documentation so its recommendations cite current guidance rather than my assumptions.

## My development process

1. **Plan first.** Architecture, demo scenario, free-tier budget and proof strategy written before code.
2. **Build behind a flag.** `USE_MOCK_DATA=true` runs the whole UI locally with zero AWS calls;
   flipping it to `false` points the identical code at live AWS.
3. **Deploy with IaC.** One `cdk deploy` provisions tables, Lambdas, API Gateway, the alarm and the
   EventBridge rule.
4. **Make the incidents real.** Rather than ship seeded demo data, I added a load generator that
   causes genuine throttling, so incidents are created by real AWS events.
5. **Then make it provable.** The verification loop and the read-only audit trail exist so that every
   claim the product makes can be independently checked.

## Who it's for

Engineering teams who carry AWS incidents, and the platform leads who have to trust automation near
production. The next step after the hackathon is a read-only pilot against one non-production
account, widening the detectors beyond DynamoDB throttling to Lambda timeouts and API error rates,
and adding application-level fixes (for example, detecting a DynamoDB 400 KB item-size failure and
proposing the S3-offload pattern).

## Try it

1. Open the dashboard: http://agentsentry-dashboard-273354655941.s3-website-us-east-1.amazonaws.com
2. **Overview** shows the counts and the latest item in each stage. The sidebar switches to the full
   history of Incidents, Pull requests, Verifications, and the Read-only audit.
3. Open [PR #4](https://github.com/sabari-07/Agentsentry/pull/4): the diagnosis quotes the real
   throttle count, and section 6 lists the AWS documentation the agent consulted at runtime.
4. **Then read the two verification comments on PR #5.** The agent
   [withheld certification](https://github.com/sabari-07/Agentsentry/pull/5#issuecomment-5864794338)
   while `ThrottledRequests` was still at 116, then
   [confirmed](https://github.com/sabari-07/Agentsentry/pull/5#issuecomment-5864880540)
   `RESOLVED_VERIFIED` once the metric reached 0. That is the whole argument of this project in two
   comments.
5. Reproduce it in your own account: `python scripts/trigger_incident.py` causes real throttling, and
   a new incident with a new PR appears within a few minutes. `README.md` and `DEPLOYMENT.md` have
   the full steps.

---

## Honesty notes

- The dashboard is served over HTTP via S3 static website hosting. AWS Amplify was the original plan;
  that account had already reached its Amplify app limit.
- The incident trigger is a deliberate load burst standing in for a traffic spike. Everything after
  it — alarm, detection, inspection, diagnosis, pull request, verification — is real and unscripted.
- The remediation PR commits an incident report documenting the change rather than mutating the live
  CDK stack, so merging is safe to demonstrate.

*Built for the AWS Zero to Shipped hackathon with Kiro and the Agent Toolkit for AWS.*
