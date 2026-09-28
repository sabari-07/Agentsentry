# AgentSentry AI — Deployment Guide

This guide covers the steps that require **your** AWS and GitHub accounts. Follow
them in order. Estimated time: ~60–90 minutes.

Prerequisites: an AWS account, the AWS CLI configured (`aws configure`), Node 20+,
Python 3.12+, and a GitHub account.

---

## Step 0 — Coding agent connection proof (REQUIRED by the hackathon)

The hackathon requires documented proof that a coding agent is connected to AWS. This project
connects the coding agent (Kiro) to the **AWS MCP Server** (Agent Toolkit for AWS).

1. Install `uv` (provides `uvx`):
   ```powershell
   irm https://astral.sh/uv/install.ps1 | iex
   ```
2. Add the AWS MCP Server to your Kiro MCP config (`.kiro/settings/mcp.json`) — already included in
   this repo:
   ```json
   {
     "mcpServers": {
       "aws-mcp": {
         "command": "C:\\Users\\<you>\\.local\\bin\\uvx.exe",
         "transport": "stdio",
         "args": [
           "mcp-proxy-for-aws-cli@latest",
           "https://aws-mcp.us-east-1.api.aws/mcp",
           "--metadata", "AWS_REGION=us-east-1"
         ],
         "env": { "AWS_PROFILE": "agentsentry" }
       }
     }
   }
   ```
3. Reconnect the server in Kiro's MCP panel (status should turn green).
4. In a new session, ask the agent an AWS question (e.g. "list my DynamoDB tables"). It should
   return the real `agentsentry-incidents` / `agentsentry-monitored` tables.

Take a **screenshot** of the connected MCP server and/or the agent returning live AWS data. Attach
it to your Builder Center submission. This is a pass/fail qualification item.

> The AWS CLI wizard `aws configure agent-toolkit` (CLI 2.35.0+) is an alternative one-command
> setup if you prefer it.

---

## Step 1 — Push the code to GitHub

```bash
cd C:\Users\DS\Desktop\hack\zero_to_zipped
git init
git add .
git commit -m "AgentSentry AI: initial commit"
git branch -M main
git remote add origin https://github.com/<your-user>/agentsentry-ai.git
git push -u origin main
```

(Making the repo public is optional per the rules, but recommended so judges can
see your development process.)

---

## Step 2 — Deploy the AWS backend (CDK)

First set up an isolated AWS profile so CDK targets the right account (not your default CLI
account). From `backend/`, `python scripts\setup_profile.py` reads `config/.env` and creates a
named profile `agentsentry`. Then:

```powershell
cd infra
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# One-time per account/region:
cdk bootstrap --profile agentsentry

# Deploy (uses the venv's Python as the CDK app):
cdk deploy --app ".venv\Scripts\python.exe app.py" --profile agentsentry --require-approval never
```

When it finishes, CDK prints outputs. **Copy the `ApiUrl` value** — you need it for the frontend:

```
AgentSentryStack.ApiUrl = https://6klp6vbzza.execute-api.us-east-1.amazonaws.com/
```

Notes on the Lambda bundling (already handled in `infra/agentsentry/stack.py`):
- Dependencies are installed into the asset at synth time (`pip install -r requirements.txt`).
- Linux wheels are pulled (`--platform manylinux2014_x86_64 --python-version 3.12
  --only-binary=:all:`) so compiled packages like `pydantic-core` work on Lambda.
- `AssetHashType.OUTPUT` ensures CDK detects bundled-content changes and updates the Lambda.

---

## Step 3 — Backend setup + configure GitHub for real PRs

```powershell
cd ..\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config\.env.example config\.env
```

Fill in `backend/config/.env`:

```
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
USE_MOCK_DATA=false

# Required for the pipeline to open REAL remediation PRs:
GITHUB_TOKEN=<classic PAT with 'repo' scope>
GITHUB_REPO=<your-user>/<your-repo>
GITHUB_BASE_BRANCH=main
```

Verify both credentials sets before deploying:

```powershell
python scripts\verify_credentials.py   # confirms AWS account
python scripts\verify_github.py        # confirms token + repo access
```

> The CDK reads the GitHub values from `config/.env` at synth time and sets them as Lambda
> environment variables, so the token is never committed. Use a short-lived token and revoke it
> after the hackathon. (For production, use AWS Secrets Manager instead.)

Verify the API is live:

```powershell
curl https://6klp6vbzza.execute-api.us-east-1.amazonaws.com/api/health
curl https://6klp6vbzza.execute-api.us-east-1.amazonaws.com/api/incidents
```

*(Optional)* `python scripts\seed_incidents.py` writes illustrative demo incidents. Not needed —
the live trigger in Step 7 produces genuine incidents.

---

## Step 4 — Deploy the frontend to Amazon S3 (THE SHIP GATE)

The dashboard is deployed as a static site to S3. (AWS Amplify was the original plan, but the
target account had reached its Amplify app limit; S3 static hosting satisfies the same Ship Gate.
`amplify.yml` is kept in the repo for anyone who prefers Amplify.)

1. Build the frontend with the live API URL:
   ```powershell
   cd frontend
   npm install
   copy .env.example .env
   # set VITE_API_BASE_URL=https://6klp6vbzza.execute-api.us-east-1.amazonaws.com
   npm run build
   ```
2. Deploy `dist/` to S3 (creates the bucket, enables website hosting, applies a public-read
   policy, and syncs the build):
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy_s3.ps1
   ```
3. The script prints the public URL:
   ```
   http://agentsentry-dashboard-273354655941.s3-website-us-east-1.amazonaws.com
   ```

**Test it in an incognito window.** If a stranger can open it and the incidents load, you have
passed the Ship Gate.

**CORS:** the API's FastAPI CORS is set to `*` (via the Lambda env in the CDK stack) so the S3
site can call the HTTPS API cross-origin without the browser preflight failing.

*(Optional, for HTTPS):* put a CloudFront distribution in front of the bucket for an `https://` URL.

---

## Step 5 — Wire the merge → verify loop (optional but high-impact)

The `.github/workflows/deploy-and-verify.yml` workflow is **manual** (`workflow_dispatch`) so it
never fails on pushes that lack AWS credentials. It deploys the CDK stack and invokes the
verification Lambda to close the loop.

To enable it:
- Add the repo secret `AWS_DEPLOY_ROLE_ARN` — an IAM role ARN GitHub can assume via OIDC (or
  switch the workflow to static access keys).
- Run it from the GitHub **Actions** tab → "Deploy and Verify" → **Run workflow**, optionally
  passing an `incident_id` (e.g. `INC-1001`) to verify after deploy.
- To make it automatic on merge, change the trigger back to `push` on `main`.

---

## Step 7 — Run the live demo (and capture every proof)

This is the sequence to record for the demo video. Everything here is genuinely live: a real
write burst causes real DynamoDB throttling, which fires a real CloudWatch alarm, which drives the
agent pipeline. Nothing is seeded or faked.

### The demo sequence

```powershell
cd backend
$env:USE_MOCK_DATA="false"

# 1. Start from a clean board (optional, makes the demo obvious)
python scripts\clear_incidents.py

# 2. Cause a REAL incident: burst writes against a 1-WCU table -> real throttling
python scripts\trigger_incident.py
#    -> prints e.g. "ok=779, throttled=21"  (real ProvisionedThroughputExceededException)

# 3. Wait ~1-3 minutes for the CloudWatch alarm -> EventBridge -> incident Lambda.
#    Refresh the dashboard: a new incident appears on its own, with a real diagnosis
#    and a link to a real GitHub PR.

# 4. Inspect what the pipeline produced
python scripts\check_live.py     # incident, status, PR url, read-only audit calls
python scripts\check_pr.py       # PR title/branch/files + body content checks

# 5. Close the loop: verification re-reads the live metric (now recovered)
python scripts\verify_now.py
#    -> status: RESOLVED_VERIFIED, observed ThrottledRequests 0.0
```

On screen, the incident moves **Active → Open PR → Verified Resolution**, and the dashboard's
read-only audit panel shows the exact API calls the agent made.

### Capture these four proofs

| Proof | Where to capture it |
|---|---|
| **1. Coding-agent connection** (required) | Kiro MCP panel showing `aws-mcp` connected, plus a session where the agent answers an AWS question with live data (e.g. lists your DynamoDB tables). |
| **2. Ship Gate** | The live S3 dashboard URL open in an **incognito** window with incidents loaded. |
| **3. Real remediation PR** | Open the PR's **Files changed** tab. It must show both the actual `infra/agentsentry/stack.py` change (`PROVISIONED` + fixed RCU/WCU → `PAY_PER_REQUEST`) and `remediations/INC-*.md`. The PR body must include diagnosis, `cdk diff`, cost delta, and rollback. PRs #1–#7 predate this upgrade and are report-only; do not use them as proof of a merge-ready fix. |
| **4. Verified resolution** | The dashboard's **Verified Resolutions** card (metric + timestamp), and/or the `verify_now.py` output showing `RESOLVED_VERIFIED` with the observed metric value. |

### Optional: CloudTrail read-only evidence ($0)

To show the agent only ever *inspected* AWS:

1. AWS Console → **CloudTrail** → **Event history** (free; no trail, no S3 bucket, no data events).
2. Filter by **User name** = the Lambda role / `agentsentry-agent`, over the incident's time window.
3. Screenshot the result: every event is `Describe*` / `Get*` / `List*` — no mutating calls.

The dashboard's **Read-only audit** view shows the same evidence in-product.

---

## Step 8 — Submission checklist (Builder Center)

- [ ] Live S3 website URL works in incognito with incidents loading (Ship Gate).
- [ ] AWS MCP connection screenshot attached (agent connected + returning live AWS data).
- [ ] Real remediation PR link/screenshot (diagnosis + `cdk diff` + cost delta + rollback).
- [ ] Verified resolution screenshot (`RESOLVED_VERIFIED` with the observed metric + timestamp).
- [ ] *(Optional)* CloudTrail Event history screenshot showing only read-only calls.
- [ ] Category tag `#workplace-efficiency` + lane tag `#startups`.
- [ ] Write-up covers: what it does, your dev process, how the coding agent
      helped, category + lane, and the live URL.
- [ ] Demo video showing incident → PR → verified resolution.
- [ ] Original app, not previously published.

Deadline: **October 2**.
