from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..agents import devsecops, kyb_underwriting, orchestrator, talent_matchmaker
from ..agents.base import notify
from ..core import ledger, vault
from ..core.db import get_db
from ..core.security import hash_password, require_roles
from ..models import AccessGrant, CandidateProfile, Company, Document, Job, Match, Reference, User, now
from ..services.watermark import watermark

router = APIRouter(prefix="/employer", tags=["Employer"])
emp = require_roles("employer_admin", "recruiter")
emp_admin = require_roles("employer_admin")


def company_out(c: Company) -> dict:
    return {"id": c.id, "name": c.name, "pan_masked": vault.mask_pan(c.pan), "cin": c.cin, "gstin": c.gstin, "domain": c.domain,
            "website": c.website, "revenue_bracket": c.revenue_bracket, "headcount": c.headcount, "vertical": c.vertical,
            "incorporation_year": c.incorporation_year, "locations": c.locations, "kyb_status": c.kyb_status,
            "risk_score": c.risk_score, "kyb_report": c.kyb_report}


def require_verified(user: User, db: Session) -> Company:
    co = db.get(Company, user.company_id)
    if co.kyb_status != "approved":
        raise HTTPException(403, f"Company KYB status is '{co.kyb_status}'. Only KYB-approved employers can access candidate data.")
    return co


@router.get("/company", summary="My company and KYB report")
def company(user: User = Depends(emp), db: Session = Depends(get_db)):
    return company_out(db.get(Company, user.company_id))


@router.post("/company/kyb", summary="Re-run the KYB Underwriting agent")
def rerun_kyb(user: User = Depends(emp_admin), db: Session = Depends(get_db)):
    return kyb_underwriting.run(db, user.company_id)


class RecruiterIn(BaseModel):
    email: EmailStr
    full_name: str
    password: str


@router.post("/recruiters", summary="Add a recruiter sub-account (must use the corporate domain)")
def add_recruiter(body: RecruiterIn, user: User = Depends(emp_admin), db: Session = Depends(get_db)):
    co = db.get(Company, user.company_id)
    if body.email.split("@")[-1].lower() != co.domain:
        raise HTTPException(400, f"Recruiters must use an @{co.domain} email")
    if db.query(User).filter_by(email=body.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    r = User(email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password),
             role="recruiter", company_id=co.id)
    db.add(r); db.commit()
    ledger.record(db, user.id, "rbac.add_recruiter", target=f"user:{r.id}", details={"email": r.email})
    return {"id": r.id, "email": r.email, "role": r.role}


@router.get("/recruiters", summary="Recruiter sub-accounts")
def recruiters(user: User = Depends(emp), db: Session = Depends(get_db)):
    return [{"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role}
            for u in db.query(User).filter_by(company_id=user.company_id).all()]


# ---------- Jobs ----------
class JobPrompt(BaseModel):
    prompt: str


@router.post("/jobs/draft", summary="Prompt-to-JD: AI structures a rough prompt into a requisition")
def draft_job(body: JobPrompt, user: User = Depends(emp)):
    return talent_matchmaker.structure_job(body.prompt)


class JobIn(BaseModel):
    title: str
    description: str = ""
    raw_prompt: str = ""
    skills: list[str] = []
    location: str = ""
    min_exp: float = 0
    max_exp: float = 30
    ctc_min_lpa: float | None = None
    ctc_max_lpa: float | None = None
    min_trust: int = 0
    require_pan: bool = False
    require_degree: bool = False
    min_refs: int = 0


def job_out(db: Session, j: Job) -> dict:
    ms = db.query(Match).filter_by(job_id=j.id).all()
    return {"id": j.id, "title": j.title, "description": j.description, "skills": j.skills, "location": j.location,
            "min_exp": j.min_exp, "max_exp": j.max_exp, "ctc_min_lpa": j.ctc_min_lpa, "ctc_max_lpa": j.ctc_max_lpa,
            "min_trust": j.min_trust, "require_pan": j.require_pan, "require_degree": j.require_degree,
            "min_refs": j.min_refs, "status": j.status, "created_at": j.created_at.isoformat(),
            "pipeline": {s: sum(1 for m in ms if m.status == s) for s in ["suggested", "shortlisted", "interview", "archived"]}}


@router.post("/jobs", summary="Create a job; Matchmaker agent surfaces top-10 verified candidates")
def create_job(body: JobIn, user: User = Depends(emp), db: Session = Depends(get_db)):
    require_verified(user, db)
    from ..services.embeddings import embed, normalize_skill
    j = Job(company_id=user.company_id, created_by=user.id, **{**body.model_dump(), "skills": [normalize_skill(s) for s in body.skills]})
    j.embedding = embed(f"{j.title} {j.description} {' '.join(j.skills)}")
    db.add(j); db.commit()
    ledger.record(db, user.id, "job.create", target=f"job:{j.id}", details={"title": j.title})
    talent_matchmaker.match_job(db, j.id)
    return job_out(db, j)


@router.get("/jobs", summary="Job requisition pipeline")
def list_jobs(user: User = Depends(emp), db: Session = Depends(get_db)):
    return [job_out(db, j) for j in db.query(Job).filter_by(company_id=user.company_id).order_by(Job.created_at.desc())]


@router.post("/jobs/{job_id}/rematch", summary="Re-run matching for a job")
def rematch(job_id: str, user: User = Depends(emp), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j or j.company_id != user.company_id:
        raise HTTPException(404)
    talent_matchmaker.match_job(db, job_id)
    return job_out(db, j)


def _card(db: Session, m: Match, p: CandidateProfile, u: User) -> dict:
    b = m.breakdown or {}
    return {"match_id": m.id, "candidate_id": u.id, "name": u.full_name, "headline": p.headline, "city": p.city,
            "years_experience": p.years_experience, "skills": p.skills, "trust_score": p.trust_score,
            "score": m.score, "status": m.status, "reasons": b.get("reasons", []), "components": b.get("components", {}),
            "badges": b.get("badges", []), "outreach_draft": m.outreach_draft, "interview_at": m.interview_at,
            "exact": b.get("exact", True)}


@router.get("/jobs/{job_id}/matches", summary="AI-matched candidate feed with explainable scores")
def job_matches(job_id: str, status: str | None = None, user: User = Depends(emp), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j or j.company_id != user.company_id:
        raise HTTPException(404)
    q = db.query(Match).filter_by(job_id=job_id)
    if status:
        q = q.filter_by(status=status)
    out = []
    for m in q.order_by(Match.score.desc()).all():
        u = db.get(User, m.candidate_id)
        out.append(_card(db, m, u.profile, u))
    return out


class SwipeIn(BaseModel):
    action: str  # shortlist (right) | archive (left) | interview (up)


@router.post("/matches/{match_id}/swipe", summary="Swipe-to-shortlist (right) / pass (left) / AI-scheduled interview (up)")
def swipe(match_id: str, body: SwipeIn, user: User = Depends(emp), db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    if not m:
        raise HTTPException(404)
    j = db.get(Job, m.job_id)
    if j.company_id != user.company_id:
        raise HTTPException(404)
    mapping = {"shortlist": "shortlisted", "right": "shortlisted", "archive": "archived", "left": "archived",
               "interview": "interview", "up": "interview"}
    if body.action not in mapping:
        raise HTTPException(400, "action must be shortlist|archive|interview")
    m.status = mapping[body.action]
    if m.status == "interview":
        # AI scheduler: next working day, 11:00 IST, avoiding already-booked slots
        taken = {x.interview_at for x in db.query(Match).filter(Match.job_id == j.id, Match.interview_at != "").all()}
        t = now() + timedelta(days=1)
        slot_h = 11
        while True:
            while t.weekday() >= 5:
                t += timedelta(days=1)
            slot = t.strftime(f"%Y-%m-%d {slot_h:02d}:00 IST")
            if slot not in taken:
                break
            slot_h += 1
            if slot_h > 17:
                slot_h, t = 11, t + timedelta(days=1)
        m.interview_at = slot
        co = db.get(Company, j.company_id)
        notify(db, m.candidate_id, f"Interview invite: {j.title} at {co.name}", f"Proposed slot {slot}. Reply in Support to reschedule.", "job")
        if not db.query(AccessGrant).filter_by(candidate_id=m.candidate_id, company_id=co.id, status="pending").first():
            db.add(AccessGrant(candidate_id=m.candidate_id, company_id=co.id, requested_by=user.id, job_id=j.id,
                               doc_types=["resume", "degree", "experience_letter", "pan"], reveal_identity_numbers=True,
                               reason=f"Interview scheduled for {j.title}"))
    db.commit()
    ledger.record(db, user.id, f"pipeline.{m.status}", subject_id=m.candidate_id, target=f"job:{j.id}",
                  details={"interview_at": m.interview_at})
    u = db.get(User, m.candidate_id)
    return _card(db, m, u.profile, u)


# ---------- Search ----------
class SearchIn(BaseModel):
    query: str
    limit: int = 20


@router.post("/search", summary="Natural-language hybrid (vector + structured) talent search")
def search(body: SearchIn, request: Request, user: User = Depends(emp), db: Session = Depends(get_db)):
    require_verified(user, db)
    res = talent_matchmaker.search(db, body.query, limit=min(body.limit, 50))
    ledger.record(db, user.id, "search.query", target="talent", details={"q": body.query[:200], "n": len(res["results"])})
    return res


# ---------- Candidate vault access ----------
def active_grant(db: Session, company_id: str, candidate_id: str) -> AccessGrant | None:
    g = (db.query(AccessGrant).filter_by(company_id=company_id, candidate_id=candidate_id, status="granted")
         .order_by(AccessGrant.decided_at.desc()).first())
    if g and g.expires_at and g.expires_at < now():
        g.status = "expired"; db.commit()
        return None
    return g


def _mask_email(e: str) -> str:
    n, d = e.split("@")
    return f"{n[0]}{'•' * max(2, len(n) - 1)}@{d}"


@router.get("/candidates/{cid}", summary="Candidate profile (PII masked unless a consent grant is active)")
def candidate_view(cid: str, user: User = Depends(emp), db: Session = Depends(get_db)):
    co = require_verified(user, db)
    if devsecops.check_scrape(db, f"user:{user.id}", cid):
        user.is_blocked = True; db.commit()
        raise HTTPException(429, "Access paused by the security agent: scraping pattern detected")
    u = db.get(User, cid)
    if not u or u.role != "candidate":
        raise HTTPException(404)
    p = u.profile
    g = active_grant(db, co.id, cid)
    ledger.record(db, user.id, "profile.view", subject_id=cid, target=f"candidate:{cid}", details={"company": co.name})
    docs = db.query(Document).filter_by(owner_id=cid).all()
    refs = db.query(Reference).filter_by(candidate_id=cid).all()
    pending = db.query(AccessGrant).filter_by(company_id=co.id, candidate_id=cid, status="pending").first()
    return {
        "id": cid, "name": u.full_name, "headline": p.headline, "city": p.city, "years_experience": p.years_experience,
        "skills": p.skills, "experience": p.experience, "education": p.education, "trust_score": p.trust_score,
        "trust_breakdown": p.trust_breakdown, "summary": (p.standardized_profile or {}).get("executive_summary", p.summary),
        "verification": {"aadhaar": p.aadhaar_verified, "pan": p.pan_verified, "photo": p.photo_verified,
                         "degree": p.degree_verified, "experience": p.experience_verified, "ctc": p.ctc_verified},
        "masked": {"email": _mask_email(u.email), "phone": (p.phone[:2] + "••••••" + p.phone[-2:]) if p.phone else "",
                   "pan": p.pan_masked, "aadhaar": p.aadhaar_masked,
                   "current_ctc": "••.• LPA" if p.current_ctc_lpa else "", "expected_ctc_lpa": p.expected_ctc_lpa},
        "documents": [{"id": d.id, "doc_type": d.doc_type, "status": d.status, "badge": bool(d.badge),
                       "accessible": bool(g and (d.doc_type in (g.doc_types or []))) and d.doc_type != "aadhaar"} for d in docs
                      if d.doc_type != "photo"],
        "references": [{"name": r.name, "company": r.company, "relationship": r.relationship_, "status": r.status,
                        "rating": r.rating if r.status == "verified" else None} for r in refs],
        "grant": {"status": g.status, "doc_types": g.doc_types, "expires_at": g.expires_at.isoformat(),
                  "reveal_identity_numbers": g.reveal_identity_numbers} if g else None,
        "pending_request": bool(pending),
    }


class AccessReq(BaseModel):
    doc_types: list[str] = ["resume", "degree", "experience_letter"]
    reason: str = ""
    job_id: str | None = None
    reveal_identity_numbers: bool = False


@router.post("/candidates/{cid}/access-request", summary="Request consent to view vault documents")
def request_access(cid: str, body: AccessReq, user: User = Depends(emp), db: Session = Depends(get_db)):
    co = require_verified(user, db)
    if "aadhaar" in body.doc_types:
        raise HTTPException(400, "Aadhaar images are never shared; masked Aadhaar status is visible on the profile")
    g = AccessGrant(candidate_id=cid, company_id=co.id, requested_by=user.id, job_id=body.job_id,
                    doc_types=body.doc_types, reason=body.reason, reveal_identity_numbers=body.reveal_identity_numbers)
    db.add(g); db.commit()
    ledger.record(db, user.id, "consent.request", subject_id=cid, target=f"grant:{g.id}",
                  details={"company": co.name, "docs": body.doc_types})
    notify(db, cid, f"{co.name} requests access to your vault", f"{', '.join(body.doc_types)} — {body.reason}", "consent")
    db.commit()
    return {"id": g.id, "status": g.status}


class RevealIn(BaseModel):
    field: str  # email | phone | pan | current_ctc


@router.post("/candidates/{cid}/reveal", summary="Hold-to-reveal a masked field (audited; needs active consent)")
def reveal(cid: str, body: RevealIn, user: User = Depends(emp), db: Session = Depends(get_db)):
    co = require_verified(user, db)
    g = active_grant(db, co.id, cid)
    if not g:
        raise HTTPException(403, "No active consent grant from this candidate")
    if body.field == "pan" and not g.reveal_identity_numbers:
        raise HTTPException(403, "Candidate has not consented to reveal identity numbers")
    u = db.get(User, cid)
    p = u.profile
    val = {"email": u.email, "phone": p.phone, "current_ctc": f"{p.current_ctc_lpa} LPA" if p.current_ctc_lpa else "",
           "pan": vault.open_field(p.pan_sealed, cid) if p.pan_sealed else p.pan_masked}.get(body.field)
    if val is None:
        raise HTTPException(400, "Unknown field")
    ev = ledger.record(db, user.id, "pii.reveal", subject_id=cid, target=f"field:{body.field}", details={"company": co.name})
    return {"field": body.field, "value": val, "audit_seq": ev.seq, "ttl_seconds": 10}


@router.get("/documents/{doc_id}/view", summary="View a consented document with dynamic watermark")
def view_document(doc_id: str, user: User = Depends(emp), db: Session = Depends(get_db)):
    co = require_verified(user, db)
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404)
    g = active_grant(db, co.id, d.owner_id)
    if not g or d.doc_type not in (g.doc_types or []) or d.doc_type == "aadhaar":
        raise HTTPException(403, "No active consent for this document")
    ev = ledger.record(db, user.id, "document.view", subject_id=d.owner_id, target=f"document:{d.id}",
                       details={"company": co.name, "doc_type": d.doc_type})
    data = vault.get(d.storage_key, d.wrapped_dek, d.kek_version, d.owner_id)
    label = f"audit#{ev.seq} · {user.email} · {ev.ts:%Y-%m-%d %H:%M} UTC · {co.name}"
    out, mime = watermark(data, d.mime, label)
    return Response(out, media_type=mime, headers={"Cache-Control": "no-store", "X-Audit-Seq": str(ev.seq)})


@router.get("/analytics", summary="Hiring analytics")
def analytics(user: User = Depends(emp), db: Session = Depends(get_db)):
    jobs = db.query(Job).filter_by(company_id=user.company_id).all()
    ms = db.query(Match).filter(Match.job_id.in_([j.id for j in jobs])).all() if jobs else []
    grants = db.query(AccessGrant).filter_by(company_id=user.company_id).all()
    return {"open_jobs": sum(j.status == "open" for j in jobs), "ai_matches": len(ms),
            "shortlisted": sum(m.status == "shortlisted" for m in ms), "interviews": sum(m.status == "interview" for m in ms),
            "avg_match_score": round(sum(m.score for m in ms) / len(ms), 1) if ms else 0,
            "consent": {s: sum(g.status == s for g in grants) for s in ["pending", "granted", "denied", "revoked", "expired"]},
            "avg_trust_of_matches": round(sum(db.get(CandidateProfile, m.candidate_id).trust_score for m in ms) / len(ms), 1) if ms else 0,
            "bgv_turnaround": "instant (pre-verified) vs 14-day industry baseline"}
