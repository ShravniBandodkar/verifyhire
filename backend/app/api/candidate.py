from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..agents import kyc_forensics, orchestrator, reference_tenure, resume_architect
from ..core import ledger, vault
from ..core.db import get_db
from ..core.security import require_roles
from ..models import (AccessGrant, AuditEvent, CandidateProfile, Company, Document, Job, Match, Notification,
                      Reference, User, now)
from ..services.docs import sniff_mime, unzip_bundle
from ..services.gov import get_gov_adapter

router = APIRouter(prefix="/candidate", tags=["Candidate"])
cand = require_roles("candidate")
MAX_FILE = 15 * 1024 * 1024
DOC_TYPES = {"auto", "aadhaar", "pan", "resume", "degree", "experience_letter", "payslip", "photo", "other"}


def doc_out(d: Document) -> dict:
    return {"id": d.id, "doc_type": d.doc_type, "filename": d.filename, "mime": d.mime, "size": d.size, "status": d.status,
            "extracted": d.extracted, "forensics": {k: v for k, v in (d.forensics or {}).items() if k != "llm"},
            "badge": d.badge, "created_at": d.created_at.isoformat()}


def profile_out(db: Session, u: User, p: CandidateProfile) -> dict:
    return {"id": u.id, "full_name": u.full_name, "email": u.email, "phone": p.phone, "city": p.city, "dob": p.dob,
            "headline": p.headline, "summary": p.summary, "years_experience": p.years_experience,
            "current_ctc_lpa": p.current_ctc_lpa, "expected_ctc_lpa": p.expected_ctc_lpa, "ctc_verified": p.ctc_verified,
            "skills": p.skills, "education": p.education, "experience": p.experience,
            "aadhaar_masked": p.aadhaar_masked, "aadhaar_verified": p.aadhaar_verified,
            "pan_masked": p.pan_masked, "pan_verified": p.pan_verified, "photo_verified": p.photo_verified,
            "degree_verified": p.degree_verified, "experience_verified": p.experience_verified,
            "trust_score": p.trust_score, "trust_breakdown": p.trust_breakdown, "gaps": p.gaps,
            "standardized_profile": p.standardized_profile, "open_to_work": p.open_to_work}


@router.get("/profile", summary="My verified profile, Trust Score and gaps")
def get_profile(user: User = Depends(cand), db: Session = Depends(get_db)):
    p = db.get(CandidateProfile, user.id)
    if not p.trust_breakdown:
        resume_architect.run(db, user.id)
    return profile_out(db, user, p)


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    city: str | None = None
    dob: str | None = None
    headline: str | None = None
    summary: str | None = None
    years_experience: float | None = None
    current_ctc_lpa: float | None = None
    expected_ctc_lpa: float | None = None
    skills: list[str] | None = None
    experience: list[dict] | None = None
    education: list[dict] | None = None
    open_to_work: bool | None = None


@router.patch("/profile", summary="Update profile fields (Architect agent re-scores automatically)")
def update_profile(body: ProfileUpdate, bg: BackgroundTasks, user: User = Depends(cand), db: Session = Depends(get_db)):
    p = db.get(CandidateProfile, user.id)
    data = body.model_dump(exclude_none=True)
    if "full_name" in data:
        user.full_name = data.pop("full_name")
    if "current_ctc_lpa" in data and data["current_ctc_lpa"] != p.current_ctc_lpa:
        p.ctc_verified = False  # self-declared change invalidates proof
    for k, v in data.items():
        if k == "experience":  # can't self-mark verified
            v = [{**e, "verified": False} for e in v]
        if k == "education":
            v = [{**e, "verified": False} for e in v]
        setattr(p, k, v)
    db.commit()
    resume_architect.run(db, user.id)
    bg.add_task(orchestrator.bg_rematch_all)
    return profile_out(db, user, p)


async def _store(db: Session, user: User, filename: str, data: bytes, doc_type: str) -> Document:
    if len(data) > MAX_FILE:
        raise HTTPException(413, f"{filename}: file too large (15 MB max)")
    mime = sniff_mime(filename, data)
    if mime == "application/octet-stream":
        raise HTTPException(415, f"{filename}: unsupported file type")
    blob = vault.put(data, user.id)
    d = Document(owner_id=user.id, doc_type=doc_type, filename=filename[:250], mime=mime, size=blob.size,
                 sha256=blob.sha256, storage_key=blob.key, wrapped_dek=blob.wrapped_dek, kek_version=blob.kek_version)
    db.add(d); db.commit()
    ledger.record(db, user.id, "document.upload", subject_id=user.id, target=f"document:{d.id}",
                  details={"filename": d.filename, "sha256": d.sha256})
    return d


@router.post("/documents", summary="Upload one document; the agent pipeline verifies it")
async def upload_document(file: UploadFile = File(...), doc_type: str = Form("auto"), sync: bool = Form(True),
                          bg: BackgroundTasks = None, user: User = Depends(cand), db: Session = Depends(get_db)):
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, f"doc_type must be one of {sorted(DOC_TYPES)}")
    d = await _store(db, user, file.filename, await file.read(), doc_type)
    if sync:
        result = orchestrator.process_document(db, d.id)
        db.refresh(d)
        return {"document": doc_out(d), "pipeline": result}
    bg.add_task(orchestrator.bg_process_document, d.id)
    return {"document": doc_out(d), "pipeline": "queued"}


@router.post("/documents/bulk", summary="Drag-and-drop multi-file or ZIP ingest; agents classify every file")
async def bulk_upload(files: list[UploadFile] = File(...), bg: BackgroundTasks = None,
                      user: User = Depends(cand), db: Session = Depends(get_db)):
    items: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if f.filename.lower().endswith(".zip") or data[:4] == b"PK\x03\x04" and not f.filename.lower().endswith(".docx"):
            items += unzip_bundle(data)
        else:
            items.append((f.filename, data))
    docs, errors = [], []
    for name, data in items[:40]:
        try:
            docs.append(await _store(db, user, name, data, "auto"))
        except HTTPException as e:
            errors.append(e.detail)
    results = [orchestrator.process_document(db, d.id) for d in docs]
    return {"processed": len(results), "results": results, "errors": errors}


@router.get("/documents", summary="List my vault documents")
def list_documents(user: User = Depends(cand), db: Session = Depends(get_db)):
    return [doc_out(d) for d in db.query(Document).filter_by(owner_id=user.id).order_by(Document.created_at.desc())]


@router.post("/documents/{doc_id}/reverify", summary="Re-run the KYC forensics pipeline")
def reverify(doc_id: str, user: User = Depends(cand), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or d.owner_id != user.id:
        raise HTTPException(404)
    return orchestrator.process_document(db, d.id)


@router.delete("/documents/{doc_id}", summary="Delete a document (DPDP right to erasure)")
def delete_document(doc_id: str, user: User = Depends(cand), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or d.owner_id != user.id:
        raise HTTPException(404)
    db.delete(d); db.commit()
    ledger.record(db, user.id, "document.erase", subject_id=user.id, target=f"document:{doc_id}")
    resume_architect.run(db, user.id)
    return {"ok": True}


@router.get("/documents/{doc_id}/raw", summary="Download my own document (decrypted)")
def own_raw(doc_id: str, user: User = Depends(cand), db: Session = Depends(get_db)):
    from fastapi.responses import Response
    d = db.get(Document, doc_id)
    if not d or d.owner_id != user.id:
        raise HTTPException(404)
    return Response(vault.get(d.storage_key, d.wrapped_dek, d.kek_version, d.owner_id), media_type=d.mime)


# ---------- Aadhaar OTP e-KYC (DigiLocker / UIDAI sandbox) ----------
class AadhaarReq(BaseModel):
    aadhaar_number: str
    otp: str | None = None


@router.post("/kyc/aadhaar/otp", summary="Step 1: request Aadhaar OTP (sandbox OTP 123456)")
def aadhaar_otp(body: AadhaarReq, user: User = Depends(cand)):
    r = get_gov_adapter().aadhaar_send_otp(body.aadhaar_number)
    if not r["ok"]:
        raise HTTPException(400, r["error"])
    return r


@router.post("/kyc/aadhaar/verify", summary="Step 2: verify OTP; only masked + tokenised Aadhaar is stored")
def aadhaar_verify(body: AadhaarReq, user: User = Depends(cand), db: Session = Depends(get_db)):
    r = get_gov_adapter().aadhaar_verify_otp(body.aadhaar_number, body.otp or "")
    if not r["ok"]:
        raise HTTPException(400, r["error"])
    num = "".join(c for c in body.aadhaar_number if c.isdigit())
    tok = vault.tokenize(num, "aadhaar")
    clash = db.query(CandidateProfile).filter(CandidateProfile.aadhaar_token == tok, CandidateProfile.user_id != user.id).first()
    if clash:
        ledger.record(db, "agent:kyc_forensics", "fraud.duplicate_aadhaar", actor_type="agent", subject_id=user.id)
        raise HTTPException(409, "This Aadhaar is already linked to another account — flagged for review")
    p = db.get(CandidateProfile, user.id)
    p.aadhaar_token, p.aadhaar_masked, p.aadhaar_verified = tok, vault.mask_aadhaar(num), True
    db.commit()
    ledger.record(db, user.id, "kyc.aadhaar_verified", subject_id=user.id, details={"masked": p.aadhaar_masked, "source": r["source"]})
    out = resume_architect.run(db, user.id)
    return {"aadhaar_masked": p.aadhaar_masked, "trust_score": out["trust_score"]}


@router.post("/kyc/liveness", summary="Selfie liveness: upload 2-5 frames captured a moment apart")
async def liveness(frames: list[UploadFile] = File(...), user: User = Depends(cand), db: Session = Depends(get_db)):
    raw = [await f.read() for f in frames[:5]]
    res = kyc_forensics.liveness_check(raw)
    p = db.get(CandidateProfile, user.id)
    if res["live"]:
        p.photo_verified = True
        await _store(db, user, "live_selfie.jpg", raw[len(raw) // 2], "photo")
        db.commit()
    ledger.record(db, "agent:kyc_forensics", "kyc.liveness", actor_type="agent", subject_id=user.id, details=res)
    res["trust_score"] = resume_architect.run(db, user.id)["trust_score"]
    return res


# ---------- References ----------
class RefIn(BaseModel):
    name: str
    email: EmailStr
    company: str
    relationship: str = "manager"


@router.post("/references", summary="Request a reference; the agent sends a signed verification link")
def add_reference(body: RefIn, user: User = Depends(cand), db: Session = Depends(get_db)):
    ref, link = reference_tenure.create_request(db, user.id, body.name, body.email, body.company, body.relationship)
    return {"id": ref.id, "status": ref.status, "verification_link": link,
            "note": "Sandbox: no email is sent; open the link to act as the referee."}


@router.get("/references", summary="My references and their verification status")
def list_references(user: User = Depends(cand), db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name, "email": r.email, "company": r.company, "relationship": r.relationship_,
             "status": r.status, "rating": r.rating, "analysis": r.analysis,
             "verified_at": r.verified_at.isoformat() if r.verified_at else None}
            for r in db.query(Reference).filter_by(candidate_id=user.id).order_by(Reference.created_at.desc())]


# ---------- Consent ----------
@router.get("/access-requests", summary="Employer access requests & grants")
def access_requests(user: User = Depends(cand), db: Session = Depends(get_db)):
    out = []
    for g in db.query(AccessGrant).filter_by(candidate_id=user.id).order_by(AccessGrant.created_at.desc()):
        if g.status == "granted" and g.expires_at and g.expires_at < now():
            g.status = "expired"
        job = db.get(Job, g.job_id) if g.job_id else None
        out.append({"id": g.id, "company": g.company.name, "company_kyb": g.company.kyb_status, "job": job.title if job else None,
                    "doc_types": g.doc_types, "reveal_identity_numbers": g.reveal_identity_numbers, "reason": g.reason,
                    "status": g.status, "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                    "created_at": g.created_at.isoformat()})
    db.commit()
    return out


class Decision(BaseModel):
    decision: str  # grant | deny | revoke
    hours: int = 72
    biometric_assertion: str = ""  # client attests FaceID/TouchID/Windows Hello/WebAuthn success


@router.post("/access-requests/{grant_id}", summary="Slide-to-consent: grant (time-bound), deny or revoke")
def decide(grant_id: str, body: Decision, user: User = Depends(cand), db: Session = Depends(get_db)):
    g = db.get(AccessGrant, grant_id)
    if not g or g.candidate_id != user.id:
        raise HTTPException(404)
    if body.decision == "grant":
        g.status, g.expires_at = "granted", now() + timedelta(hours=max(1, min(body.hours, 24 * 30)))
    elif body.decision == "deny":
        g.status = "denied"
    elif body.decision == "revoke":
        g.status = "revoked"
    else:
        raise HTTPException(400, "decision must be grant|deny|revoke")
    g.decided_at = now()
    db.commit()
    ledger.record(db, user.id, f"consent.{body.decision}", subject_id=user.id, target=f"grant:{g.id}",
                  details={"company": g.company.name, "docs": g.doc_types, "hours": body.hours,
                           "biometric": bool(body.biometric_assertion)})
    from ..agents.base import notify
    for u in db.query(User).filter_by(company_id=g.company_id).all():
        notify(db, u.id, f"{user.full_name} {g.status} your access request", ", ".join(g.doc_types), "consent")
    db.commit()
    return {"id": g.id, "status": g.status, "expires_at": g.expires_at.isoformat() if g.expires_at else None}


@router.get("/audit", summary="Real-time audit log: who viewed or requested my data")
def my_audit(limit: int = 100, user: User = Depends(cand), db: Session = Depends(get_db)):
    evs = db.query(AuditEvent).filter_by(subject_id=user.id).order_by(AuditEvent.seq.desc()).limit(min(limit, 500)).all()
    names = {}
    def actor_name(a):
        if a.startswith("agent:"):
            return a.replace("agent:", "AI · ").replace("_", " ").title()
        if a not in names:
            u = db.get(User, a)
            names[a] = (f"{u.full_name} ({u.company.name})" if u and u.company else (u.full_name if u else a))
        return names[a]
    return [{"seq": e.seq, "ts": e.ts.isoformat(), "actor": actor_name(e.actor_id), "actor_type": e.actor_type,
             "action": e.action, "target": e.target, "details": e.details, "hash": e.hash[:16]} for e in evs]


@router.get("/job-alerts", summary="AI-curated job matches for me")
def job_alerts(user: User = Depends(cand), db: Session = Depends(get_db)):
    out = []
    for m in db.query(Match).filter_by(candidate_id=user.id).order_by(Match.score.desc()).limit(20):
        j = db.get(Job, m.job_id)
        out.append({"job_id": j.id, "title": j.title, "company": j.company.name, "company_kyb": j.company.kyb_status,
                    "location": j.location, "ctc_band": [j.ctc_min_lpa, j.ctc_max_lpa], "score": m.score,
                    "status": m.status, "interview_at": m.interview_at, "reasons": (m.breakdown or {}).get("reasons", [])})
    return out


@router.get("/ctc-benchmark", summary="CTC benchmarking vs similar verified profiles")
def ctc_benchmark(user: User = Depends(cand), db: Session = Depends(get_db)):
    me = db.get(CandidateProfile, user.id)
    peers = [p for p in db.query(CandidateProfile).filter(CandidateProfile.current_ctc_lpa != None).all()  # noqa: E711
             if abs((p.years_experience or 0) - (me.years_experience or 0)) <= 2 and set(p.skills or []) & set(me.skills or [])]
    vals = sorted(p.current_ctc_lpa for p in peers)
    if not vals:
        return {"peers": 0}
    pct = lambda q: vals[min(len(vals) - 1, int(q * len(vals)))]
    mine = me.current_ctc_lpa
    rank = round(100 * sum(v <= mine for v in vals) / len(vals)) if mine else None
    return {"peers": len(vals), "p25": pct(0.25), "median": pct(0.5), "p75": pct(0.75), "p90": pct(0.9),
            "yours": mine, "your_percentile": rank, "expected": me.expected_ctc_lpa,
            "basis": f"{len(vals)} profiles within ±2 yrs experience sharing at least one skill"}
