"""End-to-end API test: exercises all seven agents through the public REST API."""
import os, sys, tempfile, time
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{TMP}/t.db", STORAGE_DIR=f"{TMP}/store", AUTO_SEED="true",
                  RATE_LIMIT_PER_MIN="100000", SCRAPE_PROFILE_VIEWS_PER_MIN="1000")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

S = Path(__file__).resolve().parent.parent / "sample_docs"
A = "/api/v1"


def login(c, email, pw):
    r = c.post(f"{A}/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_full_flow():
    with TestClient(app) as c:
        cand = login(c, "aisha@demo.example", "Candidate@123")
        hr = login(c, "hr@nimbuscloud.example", "Employer@123")
        gov = login(c, "governor@verifyhire.example", "Governor@123")
        t0 = c.get(f"{A}/candidate/profile", headers=cand).json()["trust_score"]

        # Agent 2: KYB — legit approved, shell company not approved
        cos = {x["name"]: x for x in c.get(f"{A}/admin/companies", headers=gov).json()}
        assert cos["Nimbus Cloudworks Private Limited"]["kyb_status"] == "approved"
        assert cos["Quanta Retail Analytics Private Limited"]["kyb_status"] in ("flagged", "rejected")
        qa = login(c, "quanta.hiring@gmail.com", "Employer@123")
        assert c.post(f"{A}/employer/search", json={"query": "python"}, headers=qa).status_code == 403

        # Aadhaar OTP e-KYC
        aad = (S / "README.txt").read_text().split("Verhoeff-valid): ")[1].split()[0]
        assert c.post(f"{A}/candidate/kyc/aadhaar/otp", json={"aadhaar_number": "123412341234"}, headers=cand).status_code == 400
        assert c.post(f"{A}/candidate/kyc/aadhaar/otp", json={"aadhaar_number": aad}, headers=cand).status_code == 200
        r = c.post(f"{A}/candidate/kyc/aadhaar/verify", json={"aadhaar_number": aad, "otp": "123456"}, headers=cand)
        assert r.status_code == 200 and r.json()["aadhaar_masked"].startswith("XXXX-XXXX-")

        # Agent 1 + 5 + 4: ZIP drag-and-drop ingest → classify, verify, re-score, re-match
        with open(S / "aisha_kyc_bundle.zip", "rb") as f:
            r = c.post(f"{A}/candidate/documents/bulk", files=[("files", ("bundle.zip", f.read(), "application/zip"))], headers=cand)
        assert r.status_code == 200, r.text
        print(r.json()); res = {x.get("doc_type"): x.get("verdict") for x in r.json()["results"]}
        print("bundle:", res)
        assert res.get("pan") == "verified" and res.get("degree") == "verified" and res.get("resume") == "verified"
        assert res.get("aadhaar") == "verified" and res.get("payslip") == "verified" and res.get("experience_letter") == "verified"

        # Forensics catches tampering
        for name in ["TAMPERED_degree_photoshop.pdf", "TAMPERED_pan_spliced.jpg"]:
            r = c.post(f"{A}/candidate/documents", files={"file": (name, (S / name).read_bytes())},
                       data={"doc_type": "auto"}, headers=cand).json()
            print(name, r["pipeline"]["verdict"], r["pipeline"]["risk"], r["pipeline"]["reasons"][:3])
            assert r["pipeline"]["verdict"] in ("flagged", "rejected")

        # Agent 3: reference with signed link; referee responds
        r = c.post(f"{A}/candidate/references", json={"name": "Kavita Rao", "email": "kavita@nimbuscloud.example",
                   "company": "Nimbus Cloudworks Private Limited"}, headers=cand).json()
        tok = r["verification_link"].split("token=")[1]
        assert c.get(f"{A}/public/reference/{tok}").status_code == 200
        r = c.post(f"{A}/public/reference/{tok}", json={"confirm": True, "rating": 5, "feedback": "Excellent, reliable engineer."})
        assert r.json()["status"] == "verified", r.text

        prof = c.get(f"{A}/candidate/profile", headers=cand).json()
        print("trust:", t0, "->", prof["trust_score"], [g["key"] for g in prof["gaps"]])
        assert prof["trust_score"] > t0 + 50

        # Agent 4: natural-language hybrid search with explainable scores
        q = ("Find PAN-verified full-stack engineers in Bengaluru with 4-6 years experience, verified B.Tech degree, "
             "current CTC under 22 LPA, and at least 2 verified manager references")
        r = c.post(f"{A}/employer/search", json={"query": q}, headers=hr).json()
        print("filters:", r["filters"], "latency:", r["latency_ms"], "n:", len(r["results"]))
        assert r["filters"]["city"] == "bengaluru" and r["filters"]["min_refs"] == 2 and r["filters"]["ctc_max"] == 22
        assert r["latency_ms"]["total"] < 150
        r = c.post(f"{A}/employer/search", json={"query": "react typescript engineer bengaluru"}, headers=hr).json()
        assert r["results"] and r["results"][0]["reasons"]

        # Prompt-to-JD + job creation → matches
        d = c.post(f"{A}/employer/jobs/draft", json={"prompt": "need a senior react node engineer in bengaluru 4-8 years under 35 lpa"}, headers=hr).json()
        assert "react" in d["skills"]
        j = c.post(f"{A}/employer/jobs", json={k: v for k, v in d.items() if not k.startswith("_")}, headers=hr).json()
        ms = c.get(f"{A}/employer/jobs/{j['id']}/matches", headers=hr).json()
        assert ms, "matchmaker produced no matches"
        aisha_id = c.get(f"{A}/auth/me", headers=cand).json()["id"]

        # Consent: request → candidate grants (slide-to-consent) → watermarked view → hold-to-reveal → revoke via support agent
        g = c.post(f"{A}/employer/candidates/{aisha_id}/access-request",
                   json={"doc_types": ["degree", "resume", "pan"], "reason": "Interview", "reveal_identity_numbers": True}, headers=hr).json()
        assert c.get(f"{A}/employer/candidates/{aisha_id}", headers=hr).json()["grant"] is None
        assert c.post(f"{A}/employer/candidates/{aisha_id}/reveal", json={"field": "phone"}, headers=hr).status_code == 403
        r = c.post(f"{A}/candidate/access-requests/{g['id']}", json={"decision": "grant", "hours": 24, "biometric_assertion": "webauthn"}, headers=cand)
        assert r.json()["status"] == "granted"
        view = c.get(f"{A}/employer/candidates/{aisha_id}", headers=hr).json()
        doc = next(x for x in view["documents"] if x["doc_type"] == "degree" and x["status"] == "verified")
        r = c.get(f"{A}/employer/documents/{doc['id']}/view", headers=hr)
        assert r.status_code == 200 and r.headers["x-audit-seq"]
        rv = c.post(f"{A}/employer/candidates/{aisha_id}/reveal", json={"field": "pan"}, headers=hr).json()
        assert rv["value"] == "ABCPK1234K"
        audit = c.get(f"{A}/candidate/audit", headers=cand).json()
        assert any(e["action"] == "document.view" for e in audit) and any(e["action"] == "pii.reveal" for e in audit)

        # Agent 6: support agent revokes access via tool call
        r = c.post(f"{A}/support/chat", json={"message": "Please revoke access for Nimbus"}, headers=cand).json()
        print("support:", r)
        assert r["tool"] == "revoke_access" and "revoked 1" in r["reply"]
        assert c.get(f"{A}/employer/documents/{doc['id']}/view", headers=hr).status_code == 403
        r = c.post(f"{A}/support/chat", json={"message": "what is missing from my trust score?"}, headers=cand).json()
        assert r["tool"] == "trust_status"

        # Swipe up → AI-scheduled interview
        m = c.get(f"{A}/employer/jobs/{j['id']}/matches", headers=hr).json()[0]
        r = c.post(f"{A}/employer/matches/{m['match_id']}/swipe", json={"action": "up"}, headers=hr).json()
        assert r["status"] == "interview" and "IST" in r["interview_at"]

        # Badge verification (public)
        docs = c.get(f"{A}/candidate/documents", headers=cand).json()
        b = next(d["badge"] for d in docs if d["badge"])
        assert c.post(f"{A}/public/badges/verify", json={"badge": b}).json()["valid"]
        assert not c.post(f"{A}/public/badges/verify", json={"badge": b[:-2] + "00"}).json()["valid"]

        # Developer API key access
        k = c.post(f"{A}/developer/keys", json={"name": "ci"}, headers=hr).json()["key"]
        assert c.get(f"{A}/employer/jobs", headers={"X-API-Key": k}).status_code == 200

        # Agent 7: patrol, key rotation (documents still decrypt), ledger integrity
        p = c.post(f"{A}/admin/devsecops/patrol", headers=gov).json()
        assert p["ledger"]["valid"]
        rot = c.post(f"{A}/admin/devsecops/rotate-keys", headers=gov).json()
        assert rot["rewrapped"] > 0
        did = docs[0]["id"]
        assert c.get(f"{A}/candidate/documents/{did}/raw", headers=cand).status_code == 200
        assert c.post(f"{A}/employer/candidates/{aisha_id}/reveal", json={"field": "pan"}, headers=hr).status_code == 403  # revoked
        agents = c.get(f"{A}/admin/agents", headers=gov).json()
        print({a["key"]: a["runs"] for a in agents})
        assert all(a["runs"] > 0 for a in agents), "every agent should have acted"
        assert c.get(f"{A}/admin/ledger/verify", headers=gov).json()["valid"]

        # Scraping defence
        os.environ["X"] = "1"
        from app.core.config import settings
        settings.SCRAPE_PROFILE_VIEWS_PER_MIN = 5
        rec = login(c, "recruiter@nimbuscloud.example", "Employer@123")
        ids = [x["candidate_id"] for x in c.post(f"{A}/employer/search", json={"query": "engineer", "limit": 20}, headers=rec).json()["results"]]
        codes = [c.get(f"{A}/employer/candidates/{i}", headers=rec).status_code for i in ids[:10]]
        assert 429 in codes, codes
        assert c.get(f"{A}/employer/jobs", headers=rec).status_code == 403
        print("ALL GOOD")


if __name__ == "__main__":
    test_full_flow()
