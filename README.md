# AgentSentry AI

Autonomous DevSecOps & cloud infrastructure auto-remediation copilot for the **AWS Zero to Shipped Hackathon**.

AgentSentry AI watches live AWS telemetry (CloudWatch / EventBridge), diagnoses infrastructure
incidents via read-only inspection, proposes an Infrastructure-as-Code fix as a **merge-ready
GitHub Pull Request** (with cost delta, `cdk diff`, and rollback plan), and — after a human merges —
**re-verifies the live metric** and posts a confirmed resolution. Every claim is backed by evidence.

## Two proof layers

1. **Verification loop (primary):** the live CloudWatch metric returns to healthy after the merge,
   with a timestamp. Proves the fix worked.
2. **CloudTrail read-only audit (secondary):** using free CloudTrail Event history (no trail, no S3,
   no data events), we show the agent made only `Describe*` / `Get*` / `List*` calls. Proves the
   agent was safe and only inspected. Stays 100% Free Tier.

## Project structure

```
zero_to_zipped/
├── backend/                 # Python + FastAPI API and AWS service layer
│   ├── app/
│   │   ├── api/             # FastAPI routers (incidents, prs, verification, audit)
│   │   ├── core/            # app wiring, logging
│   │   ├── models/          # pydantic schemas
│   │   └── services/        # AWS (boto3), GitHub, verification services
│   ├── config/              # settings loader + .env lives here
│   ├── main.py              # FastAPI entrypoint
│   └── requirements.txt
└── frontend/                # React + Vite dashboard
    ├── src/
    │   ├── api/             # backend API client
    │   ├── components/      # UI components (columns, cards, audit panel)
    │   ├── pages/           # Dashboard page
    │   └── types/           # shared TS types
    ├── index.html
    ├── package.json
    └── vite.config.ts
```

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config\.env.example config\.env   # then fill in credentials
python main.py                          # serves on http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
copy .env.example .env                  # set VITE_API_BASE_URL if needed
npm run dev                             # serves on http://localhost:5173
```

## Configuration

All backend credentials are read from `backend/config/.env`. See `backend/config/.env.example`
for the full list of variables. Never commit the real `.env` — it is git-ignored.
