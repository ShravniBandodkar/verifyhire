"""Agent 5 — Career & Resume Architect Agent (replaces resume writers & career coaches).

Builds the standardized verified profile from raw documents, computes the Trust Score
(0-100 verification completeness), lists missing credentials with next actions, and
re-indexes the candidate in the vector store.
"""
from sqlalchemy.orm import Session

from ..models import CandidateProfile, Document, Reference, User
from ..services import llm
from ..services.embeddings import embed, extract_skills, index
from .base import agent_run

WEIGHTS = {
    "aadhaar": (20, "Aadhaar e-KYC", "Complete Aadhaar OTP e-KYC from the Verify tab."),
    "pan": (15, "PAN verified", "Upload your PAN card — the agent validates it with NSDL."),
    "photo": (10, "Live selfie match", "Take a live selfie (liveness check) from the Verify tab."),
    "resume": (10, "Resume parsed", "Upload your latest resume (PDF/DOCX)."),
    "degree": (15, "Degree verified", "Upload your degree certificate for NAD/DigiLocker cross-check."),
    "experience": (10, "Employment verified", "Upload an experience or relieving letter from a past employer."),
    "ctc": (10, "CTC proof", "Upload a recent payslip or Form-16 (it is auto-redacted)."),
    "references": (10, "2 verified references", "Add references using their official company email."),
}


def compute_trust(db: Session, prof: CandidateProfile) -> tuple[int, dict, list]:
    has_resume = db.query(Document).filter_by(owner_id=prof.user_id, doc_type="resume", status="verified").count() > 0
    refs = db.query(Reference).filter_by(candidate_id=prof.user_id, status="verified").count()
    state = {
        "aadhaar": prof.aadhaar_verified, "pan": prof.pan_verified, "photo": prof.photo_verified,
        "resume": has_resume, "degree": prof.degree_verified, "experience": prof.experience_verified,
        "ctc": prof.ctc_verified, "references": refs,
    }
    score, breakdown, gaps = 0, {}, []
    for k, (w, label, action) in WEIGHTS.items():
        if k == "references":
            pts = min(refs, 2) * (w // 2)
        else:
            pts = w if state[k] else 0
        score += pts
        breakdown[k] = {"label": label, "points": pts, "max": w}
        if pts < w:
            gaps.append({"key": k, "label": label, "action": action, "points": w - pts})
    gaps.sort(key=lambda g: -g["points"])
    return score, breakdown, gaps


def profile_text(user: User, prof: CandidateProfile) -> str:
    exp = "; ".join(f"{e.get('title','')} at {e.get('company','')}" for e in prof.experience or [])
    edu = "; ".join(f"{e.get('degree','')} {e.get('institution','')}" for e in prof.education or [])
    return (f"{prof.headline}. {prof.summary} Skills: {', '.join(prof.skills or [])}. "
            f"Experience: {exp}. Education: {edu}. Location: {prof.city}. {prof.years_experience} years.")


def run(db: Session, user_id: str) -> dict:
    user = db.get(User, user_id)
    prof = db.get(CandidateProfile, user_id)
    if not prof:
        return {}
    with agent_run(db, "resume_architect", f"candidate:{user_id}", user_id) as tr:
        # Merge parsed resume fields into the profile (only filling blanks / unions)
        resumes = db.query(Document).filter_by(owner_id=user_id, doc_type="resume").order_by(Document.created_at.desc()).all()
        if resumes:
            r = resumes[0].extracted or {}
            prof.skills = sorted(set(prof.skills or []) | set(r.get("skills") or []))
            if not prof.years_experience and r.get("years_experience"):
                prof.years_experience = float(r["years_experience"])
            if not prof.phone and r.get("phone"):
                prof.phone = r["phone"]
            tr.step("merge_resume", skills=len(prof.skills))
        if prof.summary and not prof.skills:
            prof.skills = extract_skills(prof.summary)

        score, breakdown, gaps = compute_trust(db, prof)
        prof.trust_score, prof.trust_breakdown, prof.gaps = score, breakdown, gaps
        tr.step("trust_score", score=score, gaps=len(gaps))

        std = {
            "name": user.full_name, "headline": prof.headline or f"{(prof.skills or ['Software'])[0].title()} professional",
            "location": prof.city, "years_experience": prof.years_experience,
            "verified_skills": prof.skills, "experience": prof.experience, "education": prof.education,
            "verification": {k: v["points"] == v["max"] for k, v in breakdown.items()},
        }
        if llm.enabled():
            out = llm.complete_json(
                "You are an executive resume writer. Write factual profiles; never invent credentials.",
                f"Profile data: {std}\nWrite JSON {{\"executive_summary\": str (<=70 words), \"headline\": str (<=12 words), "
                f"\"coaching_tip\": str (<=30 words)}}", required=["executive_summary"])
            if out:
                tr.llm_used = True
                std.update(out)
        if "executive_summary" not in std:
            top = ", ".join((prof.skills or [])[:5])
            std["executive_summary"] = (f"{user.full_name} is a {prof.years_experience:g}-year professional based in "
                                        f"{prof.city or 'India'} with verified strengths in {top or 'software engineering'}. "
                                        f"Trust Score {score}/100 on VerifyHire.")
            if gaps:
                std["coaching_tip"] = f"Next best step: {gaps[0]['action']} (+{gaps[0]['points']} trust points)."
        prof.standardized_profile = std
        prof.embedding = embed(profile_text(user, prof))
        index().upsert(user_id, prof.embedding)
        db.commit()
        tr.decision = f"trust_{score}"
        tr.summary = f"Trust Score {score}/100; {len(gaps)} gaps. Top gap: {gaps[0]['label'] if gaps else 'none'}"
        tr.output = {"trust_score": score, "gaps": [g["key"] for g in gaps]}
    return {"trust_score": score, "gaps": gaps}
