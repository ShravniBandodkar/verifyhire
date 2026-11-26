# VerifyHire — AI-Native Verified Resume Registry

> **CONFIDENTIAL — Intellectual property of WildCatter Ventures.** Built in response to RFP-VH-2026-V1.0.
> Do not distribute, publish or reference without written permission.

VerifyHire is a consent-first registry of **Aadhaar & PAN-verified candidates** and **KYB-verified employers**,
operated by **seven autonomous AI agents** that do the verification, matching and support work a back office
used to do. It ships as a **web app**, a **desktop app (Windows / macOS)** and a **public REST API**.

| | |
|---|---|
| Web + API | `https://verifyhire-ndua.onrender.com` |
| Interactive API docs | `/docs` (Swagger) · `/redoc` · `/openapi.json` |
| Desktop | `desktop/` — Electron, builds `.exe` (NSIS) and `.dmg` |

## Demo accounts (sandbox, synthetic data)

| Role | Email | Password |
|---|---|---|
| Candidate (starts unverified) | `aisha@demo.example` | `Candidate@123` |
| Employer — KYB approved | `hr@nimbuscloud.example` | `Employer@123` |
| Employer — shell company, blocked by KYB agent | `quanta.hiring@gmail.com` | `Employer@123` |
| Human governor | `governor@verifyhire.example` | `Governor@123` |

Sandbox Aadhaar for Aisha and the OTP (`123456`) are in `/samples/README.txt`. Sample documents, including
deliberately **tampered** ones, are served from `/samples/`. See [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

## The seven agents

| # | Agent | Replaces | What it does autonomously |
|---|---|---|---|
| 1 | KYC & Document Forensics | KYC/BGV analyst | OCR → classify → extract → tamper forensics (edit-tool metadata, font anomalies, JPEG error-level analysis, checksums, duplicate-file & duplicate-Aadhaar detection, name cross-match) → NSDL / NAD / UIDAI checks → signed verification badge. Masks Aadhaar digits on stored images. |
| 2 | Corporate KYB Underwriting | B2B onboarding specialist | PAN entity type, GSTIN checksum & embedded-PAN match, CIN structure & year, MCA21 status/filings/capital, EPFO headcount, domain age, free-mail admins → risk score → approve / flag / reject. |
| 3 | Reference & Tenure | Reference caller | Signed single-use referee links, corporate-domain checks, reference-ring detection (shared referees, reciprocal refs, same-IP), sentiment, tenure cross-check. |
| 4 | Semantic Talent Matchmaker | Sourcer / recruiter | NL query → filters, hybrid structured + vector search, explainable scores, prompt-to-JD, proactive top-10 per job, drafted outreach. |
| 5 | Career & Resume Architect | Resume writer / coach | Standardized profile, Trust Score (0–100), ranked gaps with next actions, re-indexing. |
| 6 | Support & Dispute | Support / trust officer | Chat that acts through audited, caller-scoped tools: revoke/extend consent, re-run KYC, correct profile, explain status, escalate. |
| 7 | DevSecOps & FinOps | SRE / security analyst | Latency SLOs, rate limiting, scraper blocking, vector-index self-heal, consent expiry, ledger integrity, master-key rotation, cost view. |

Agents are LangGraph state graphs and are chained by an orchestrator graph
(`Forensics → Architect → Matchmaker`). Every decision is persisted (`/admin/runs`) and written to a
hash-chained, append-only ledger. Only flagged cases reach the human governor queue.

**LLM is optional.** Set `LLM_PROVIDER=anthropic|openai|gemini` with a key and the agents use it for
vision review of documents, query parsing, JD structuring, narratives and support replies. Without a key, every
agent falls back to its deterministic rule engine, so the demo never breaks. LLM output is always schema-checked
and bounded: deterministic checks dominate every decision.

## Run locally

```bash
# API + agents (Python 3.13, Tesseract installed)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # seeds demo data on first start

# Web client (dev server on :3000, talks to :8000)
cd frontend && npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
# …or build once and let the API serve it on :8000:  npm run build

# Desktop app
cd desktop && npm install
npm run dev                                         # points at http://localhost:8000
npm run dist:win   # or dist:mac → installers in desktop/dist

# Tests (unit + full end-to-end flow through every agent)
cd backend && pytest -q tests
```

## Deploy to Render

1. Push this repo to GitHub.
2. Render → **New → Blueprint** → select the repo. `render.yaml` builds the `Dockerfile` (Next.js static build + FastAPI + Tesseract) as one web service, with secrets auto-generated.
3. Optional: set `LLM_PROVIDER` and the matching API key in the service's environment.
4. Open the service URL. The free tier sleeps after ~15 minutes idle; the first request takes ~30–60 s to wake.
5. Point the desktop app at it: set `VH_SERVER_URL`, or use **File → Change server URL** (default `https://verifyhire-ndua.onrender.com`).

## Build on the API

```bash
TOKEN=$(curl -s -X POST $BASE/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"hr@nimbuscloud.example","password":"Employer@123"}' | jq -r .access_token)
KEY=$(curl -s -X POST $BASE/api/v1/developer/keys -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"my-app"}' | jq -r .key)
curl -s -X POST $BASE/api/v1/employer/search -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"query":"PAN-verified full-stack engineers in Bengaluru, 4-6 years, under 22 LPA"}'
```

Every screen of the web and desktop clients uses this same public API.

## Repository layout

```
backend/   FastAPI app — api/ (REST), agents/ (7 agents + orchestrator), core/ (vault, ledger, auth),
           services/ (gov adapters, OCR, embeddings/vector index, LLM, watermarking), tests/
frontend/  Next.js 14 + TypeScript + Tailwind (static export served by the API)
desktop/   Electron shell: tray, native notifications, Touch ID / Windows Hello, encrypted cache, batch ingest
docs/      ARCHITECTURE.md (incl. RFP coverage), DEMO_SCRIPT.md
```

## Sandbox boundaries (Phase 1 & 2)

Government integrations (UIDAI/DigiLocker, NSDL, MCA21, GSTN, NAD, EPFO) run through a **pluggable adapter**
with a sandbox implementation that applies the real validation algorithms (Verhoeff, GSTIN mod-36, PAN/CIN
structure) against a synthetic registry. Production adapters need licensed credentials and plug into
`services/gov.py` without other changes. Mobile apps, real biometric face-matching, Terraform IaC and
certification work (ISO 27001 / SOC 2) are scoped for Phases 3–4. See `docs/ARCHITECTURE.md`.
