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

## Step 3 — Seed live incident data

So the dashboard shows the story-driven incidents (resolved / PR-open / diagnosing):

```bash
cd ..\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Seed the live DynamoDB table (force live mode for this one command):
$env:USE_MOCK_DATA="false"; python scripts\seed_incidents.py
```

Verify the API is live:

```powershell
curl https://6klp6vbzza.execute-api.us-east-1.amazonaws.com/api/health
curl https://6klp6vbzza.execute-api.us-east-1.amazonaws.com/api/incidents
```

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

## Step 6 — Submission checklist (Builder Center)

- [ ] Live S3 website URL works in incognito with incidents loading (Ship Gate).
- [ ] AWS MCP connection screenshot attached (agent connected + returning live AWS data).
- [ ] Category tag `#workplace-efficiency` + lane tag `#startups`.
- [ ] Write-up covers: what it does, your dev process, how the coding agent
      helped, category + lane, and the live URL.
- [ ] Demo video showing incident → PR → merge → verified resolution.
- [ ] Original app, not previously published.

Deadline: **October 2**.
