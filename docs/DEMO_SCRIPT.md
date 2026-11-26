# Live demo script (~10 minutes)

Open the Render URL a minute early so the free instance is awake.

## 1. Landing (30 s)
Show the seven-agent workforce, the live counters (agent decisions, autonomy rate) and the one-click demo accounts.

## 2. Candidate: zero-touch verification (3 min) — log in as **Candidate · Aisha Kapoor**
1. **Overview.** Trust Score starts at 0. The Architect agent lists ranked next steps.
2. **Verify → Aadhaar OTP.** Enter Aisha's sandbox Aadhaar (from `/samples/README.txt`) and send the OTP. Enter `123456`. Only `XXXX-XXXX-3301` is stored.
3. **Vault.** Download `/samples/aisha_kyc_bundle.zip` and **drag the ZIP onto the drop zone.** The agents classify six files (PAN, Aadhaar, degree, experience letter, payslip, resume), OCR them, run forensics and registry checks, and issue signed badges. Open an **Agent report** to show the extracted fields and checks.
4. Drop **`TAMPERED_pan_spliced.jpg`**: rejected (Photoshop fingerprint, PAN not in NSDL). Drop **`TAMPERED_degree_photoshop.pdf`**: flagged (edit tool, 7 embedded fonts) and sent to the governor queue.
5. **Verify → References.** Add `Kavita Rao · kavita@nimbuscloud.example · Nimbus Cloudworks Private Limited`. Open the sandbox link and submit as the referee. Verified.
6. **Overview.** The Trust Score has jumped (0 → 85+). Show the CTC benchmark.

## 3. Employer: AI talent search (3 min) — log in as **Employer · Nimbus**
1. **Overview.** KYB report: every registry and consistency check the agent ran.
2. **Talent search.** Run the default RFP query (*"PAN-verified full-stack engineers in Bengaluru with 4–6 years…"*). Show the agent-parsed filters, about 10 ms latency, exact matches and explainable score bars.
3. **Jobs.** In Prompt-to-JD, click *Structure with AI*, then *Post job & match*. The **swipe deck** appears: drag right to shortlist, up for an AI-scheduled interview (watch the slot appear).
4. Open **Aisha** in a candidate drawer. Contact details, PAN and CTC are blurred; hold-to-reveal says *needs consent*. Click **Request document access**.

## 4. Consent loop (1.5 min)
1. Back as **Aisha → Consent & audit.** Pick 24 h and **slide to grant** (OS biometric prompt where available).
2. As **Nimbus**: hold-to-reveal PAN, then **View (watermarked)** degree. The stamp shows company, email, time and audit #.
3. As **Aisha**: the audit trail shows the view and reveal events. Open **Ask agent** and type *"Revoke access for Nimbus"*. The Support agent revokes it via a tool call, and the employer's next view is refused.

## 5. Shell employer (30 s) — log in as **Shell employer · Quanta**
The KYB agent rejected it (free-mail admin, invalid GSTIN checksum, CIN year ≠ declared year, EPFO shows 3 staff vs 450 declared, 0.2-year-old domain, stale filings) — risk 100. Search is locked.

## 6. Governor console (1.5 min) — log in as **Governor**
* **Agent workforce:** runs, latency and escalations per agent; autonomy rate.
* **Escalations:** the tampered degree and the reference ring (*Sunny Verma vouches for 4 candidates from a Gmail address*). Approve or reject with one click.
* **Ledger → Verify hash chain:** intact.
* **DevSecOps:** p50/p95, self-healing actions. Click **Rotate vault master key**, and documents still open afterwards.

## 7. Desktop + API (30 s)
Show the Electron app (tray, native notification on new consent, File → Batch ingest folder) and `/docs` (Swagger).
