# AgentSentry AI

Autonomous DevSecOps & cloud infrastructure auto-remediation copilot for the **AWS Zero to Shipped Hackathon**.

AgentSentry AI watches live AWS telemetry (CloudWatch / EventBridge), diagnoses infrastructure
incidents via read-only inspection, proposes an Infrastructure-as-Code fix as a **merge-ready
GitHub Pull Request** (with cost delta, `cdk diff`, and rollback plan), and — after a human merges —
**re-verifies the live metric** and posts a confirmed resolution. Every claim is backed by evidence.

## Live deployment

- **Dashboard (public, Ship Gate):** http://agentsentry-dashboard-273354655941.s3-website-us-east-1.amazonaws.com
- **API (Lambda + API Gateway):** https://6klp6vbzza.execute-api.us-east-1.amazonaws.com
- **Region / Account:** us-east-1 / 273354655941
- **Category / Lane tags:** `#workplace-efficiency` / `#startups`

The dashboard is a static React app hosted on **Amazon S3 static website hosting**. The API is a
**FastAPI app running on AWS Lambda behind an HTTP API Gateway**, backed by **DynamoDB**. The
coding agent connects to AWS through the **Agent Toolkit for AWS (AWS MCP Server)**.

## Two proof layers

1. **Verification loop (primary):** the live CloudWatch metric returns to healthy after the merge,
   with a timestamp. Proves the fix worked.
2. **CloudTrail read-only audit (secondary):** using free CloudTrail Event history (no trail, no
   dedicated bucket, no data events), we show the agent made only `Describe*` / `Get*` / `List*`
   calls. Proves the agent was safe and only inspected. Stays 100% Free Tier.

## Architecture

```
                        ┌──────────────────────────────────────────────┐
                        │            AWS (us-east-1, Free Tier)          │
                        │                                                │
  Browser ──HTTP──▶  S3 static website (React dashboard)                 │
     │                  │                                                │
     │  HTTPS (fetch)   ▼                                                │
     └────────▶  API Gateway (HTTP API)  ──▶  Lambda: agentsentry-api    │
                        │                        (FastAPI via Mangum)    │
                        │                              │                 │
                        │                              ▼                 │
                        │                     DynamoDB: agentsentry-      │
                        │                     incidents (incident store) │
                        │                                                │
   CloudWatch alarm ─▶ EventBridge ─▶ Lambda: agentsentry-incident-      │
   (ThrottledRequests   rule            handler (writes PENDING)         │
    on agentsentry-                                                      │
    monitored table)                                                    │
                        │                                                │
   GitHub Actions ─────▶ Lambda: agentsentry-verification-handler ──▶    │
   (deploy complete)     (re-checks metric, marks RESOLVED_VERIFIED)     │
                        └──────────────────────────────────────────────┘

  Coding agent (Kiro) ──AWS MCP Server (Agent Toolkit)──▶ read-only AWS API inspection
```

Deployed resources (via AWS CDK in `infra/`):

- `agentsentry-incidents` — DynamoDB table (on-demand billing), incident/PR/verification records
- `agentsentry-monitored` — DynamoDB table, the demo "victim" resource watched for throttling
- `agentsentry-api` — Lambda (FastAPI/Mangum) behind an HTTP API Gateway
- `agentsentry-incident-handler` — Lambda invoked by EventBridge on a CloudWatch alarm
- `agentsentry-verification-handler` — Lambda that runs the post-deploy verification loop
- CloudWatch alarm on `ThrottledRequests` + EventBridge rule wiring **any** account alarm to the
  incident handler

## Scope

- **Detection is account-wide.** The EventBridge rule matches any CloudWatch alarm entering `ALARM`;
  it is not pinned to one alarm or resource.
- **Resource identification** reads the resource, namespace, metric, statistic and the metric's full
  dimension set from the alarm payload, covering DynamoDB, Lambda, API Gateway (v1/v2), RDS, SQS and
  ECS. Unrecognised namespaces are still recorded, just without an automated diagnosis.
- **Remediation rules** currently cover DynamoDB throttling; other services are detection-only.
- **It only sees what you alarm on** — there is no auto-discovery of unmonitored resources.
- **Per-resource repository routing** via `RESOURCE_REPO_MAP` chooses the PR destination. The current
  concrete transformer expects `infra/agentsentry/stack.py`; a mapped repository needs that supported
  layout plus its own deployment and verification integration. Routing alone is not multi-project
  deployment.

## Tests

```bash
cd backend && pytest        # 67 tests: metrics, verification, diagnosis, MCP, PR report, routing
cd infra   && pytest        # 5 tests: EventBridge scope and IAM permissions on the synthesised stack
```

## Project structure

```
zero_to_zipped/
├── backend/                 # Python + FastAPI API and AWS service layer
│   ├── app/
│   │   ├── api/             # FastAPI routers (incidents, verification, audit, health)
│   │   ├── core/            # app wiring (container), logging
│   │   ├── models/          # pydantic schemas
│   │   └── services/        # AWS (boto3), GitHub, verification services
│   ├── config/              # settings loader + .env lives here (git-ignored)
│   ├── scripts/             # seed_incidents, setup_profile, verify_credentials
│   ├── lambda_api.py        # Lambda handler (FastAPI via Mangum)
│   ├── lambda_incident.py   # Lambda handler (EventBridge -> PENDING incident)
│   ├── lambda_verify.py     # Lambda handler (deploy complete -> verification loop)
│   ├── main.py              # local FastAPI entrypoint (uvicorn)
│   └── requirements.txt
├── frontend/                # React + Vite dashboard
│   ├── src/
│   │   ├── api/             # backend API client
│   │   ├── components/      # UI (columns, cards, read-only audit panel)
│   │   ├── pages/           # Dashboard page
│   │   └── types/           # shared TS types
│   ├── deploy_s3.ps1        # deploys dist/ to the S3 website bucket
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── infra/                   # AWS CDK (Python) — all deployed resources
│   ├── agentsentry/stack.py
│   └── app.py
├── .github/workflows/       # deploy-and-verify workflow (manual trigger)
├── amplify.yml              # Amplify build config (alternative host; see note below)
└── DEPLOYMENT.md            # full deploy guide
```

> **Hosting note:** the plan originally targeted AWS Amplify for the frontend. The target AWS
> account had reached its maximum number of Amplify apps, so the dashboard is deployed via
> **S3 static website hosting** instead (`frontend/deploy_s3.ps1`). Both satisfy the Ship Gate
> (a live app on a public AWS URL); `amplify.yml` is retained for anyone who prefers Amplify.

## Quick start (local development)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1               # Windows PowerShell
pip install -r requirements.txt
copy config\.env.example config\.env     # then fill in credentials (USE_MOCK_DATA=true for local)
python main.py                           # serves on http://localhost:8000
```

With `USE_MOCK_DATA=true` the API serves seeded demo incidents with no AWS calls, ideal for local
dev and demos.

### Frontend

```bash
cd frontend
npm install
copy .env.example .env                   # set VITE_API_BASE_URL (defaults to http://localhost:8000)
npm run dev                              # serves on http://localhost:5173
```

## Deployment

See **DEPLOYMENT.md** for the full, verified deploy path (CDK backend, seed data, S3 frontend,
and the coding-agent connection proof).

## Configuration

All backend credentials are read from `backend/config/.env`. See `backend/config/.env.example`
for the full list of variables. The real `.env` is git-ignored and must never be committed.
On Lambda, configuration is supplied via environment variables set by the CDK stack.
