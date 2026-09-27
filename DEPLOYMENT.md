# AgentSentry AI — Deployment Guide

This guide covers the steps that require **your** AWS and GitHub accounts. Follow
them in order. Estimated time: ~60–90 minutes.

Prerequisites: an AWS account, the AWS CLI configured (`aws configure`), Node 20+,
Python 3.12+, and a GitHub account.

---

## Step 0 — Coding agent connection proof (REQUIRED by the hackathon)

The hackathon requires documented proof that a coding agent is connected to AWS.

```bash
aws configure agent-toolkit
```

Take a **screenshot** of the successful CLI output. You will attach this to your
Builder Center submission. This is a pass/fail qualification item.

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

```bash
cd infra
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt

# One-time per account/region:
cdk bootstrap

cdk deploy --require-approval never
```

When it finishes, CDK prints outputs. **Copy the `ApiUrl` value** — you need it
for the frontend. Example:

```
AgentSentryStack.ApiUrl = https://abc123.execute-api.us-east-1.amazonaws.com/
```

---

## Step 3 — Seed live incident data

So the dashboard shows the story-driven incidents (resolved / PR-open / diagnosing):

```bash
cd ..\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Point config at the live table and disable mock mode:
copy config\.env.example config\.env
# Edit config\.env:  USE_MOCK_DATA=false   and   AWS_REGION=us-east-1

python scripts\seed_incidents.py
```

Verify the API is live:

```bash
curl <ApiUrl>api/health
curl <ApiUrl>api/incidents
```

---

## Step 4 — Deploy the frontend to Amplify (THE SHIP GATE)

1. Open the **AWS Amplify** console → **New app** → **Host web app**.
2. Connect your **GitHub repo** and select the `main` branch.
3. Amplify auto-detects the monorepo via `amplify.yml` (appRoot: `frontend`).
4. Under **Environment variables**, add:
   - `VITE_API_BASE_URL` = the `ApiUrl` from Step 2 (no trailing `api/`, just the base, e.g. `https://abc123.execute-api.us-east-1.amazonaws.com`)
5. Click **Save and deploy**.

Amplify builds and gives you a public URL like:
`https://main.d1234abcd.amplifyapp.com`

**Test it in an incognito window.** If a stranger can open it, you have passed
the Ship Gate.

---

## Step 5 — Wire the merge → verify loop (optional but high-impact)

The `.github/workflows/deploy-and-verify.yml` workflow runs on merge to `main`,
redeploys the stack, and invokes the verification Lambda to close the loop.

In your GitHub repo settings add:
- Secret `AWS_DEPLOY_ROLE_ARN` — an IAM role ARN GitHub can assume via OIDC
  (or switch the workflow to static access keys if you prefer).
- Optionally a repo variable `INCIDENT_ID` — the incident to verify if the merge
  commit message has no `INC-...` trailer.

To trigger the winning demo moment: open a remediation PR whose commit message
includes an `Incident: INC-...` trailer, merge it, and watch the workflow flip
that incident to `RESOLVED_VERIFIED`.

---

## Step 6 — Submission checklist (Builder Center)

- [ ] Live Amplify URL works in incognito (Ship Gate).
- [ ] `aws configure agent-toolkit` screenshot attached (agent proof).
- [ ] Category tag `#workplace-efficiency` + lane tag `#startups`.
- [ ] Write-up covers: what it does, your dev process, how the coding agent
      helped, category + lane, and the live URL.
- [ ] Demo video showing incident → PR → merge → verified resolution.
- [ ] Original app, not previously published.

Deadline: **October 2**.
