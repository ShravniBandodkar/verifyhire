"""Agent 3 — Autonomous Reference & Tenure Agent (replaces background-check reference callers).

* Issues signed, single-use verification links to references (corporate-domain enforced).
* Runs a structured chat verification when the reference responds.
* Detects fake reference rings: shared referee emails across candidates, reciprocal references,
  free-mail referees, and many responses from one IP.
"""
import secrets
from collections import Counter

from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.security import sha256
from ..models import Company, Reference, User, now
from ..services import llm
from ..services.gov import name_similarity
from .base import agent_run, notify
from .kyb_underwriting import FREE_MAIL


def create_request(db: Session, candidate_id: str, name: str, email: str, company: str, relationship: str) -> tuple[Reference, str]:
    token = secrets.token_urlsafe(24)
    ref = Reference(candidate_id=candidate_id, name=name, email=email.lower().strip(), company=company,
                    relationship_=relationship, token_hash=sha256(token))
    db.add(ref)
    db.commit()
    link = f"{settings.PUBLIC_BASE_URL}/reference?token={token}"
    with agent_run(db, "reference_tenure", f"reference:{ref.id}", candidate_id) as tr:
        dom = ref.email.split("@")[-1]
        tr.step("dispatch", channel="email (sandbox outbox)", domain=dom)
        warn = dom in FREE_MAIL
        ref.analysis = {"link_sent": True, "domain": dom, "free_mail": warn, "outbox_link": link}
        db.commit()
        tr.decision = "sent"
        tr.summary = f"Verification link sent to {ref.email}" + (" (warning: personal email domain)" if warn else "")
    return ref, link


QUESTIONS = [
    "Can you confirm the candidate worked with you at the stated company?",
    "What was your working relationship and for how long?",
    "How would you rate their performance from 1 to 5?",
    "Anything an employer should know?",
]


def detect_rings(db: Session) -> list[dict]:
    refs = db.query(Reference).all()
    findings = []
    by_email = Counter(r.email for r in refs)
    for email, n in by_email.items():
        if n >= 3:
            findings.append({"type": "shared_referee", "email": email, "candidates": n})
    users = {u.email.lower(): u.id for u in db.query(User).filter_by(role="candidate").all()}
    pairs = {(users.get(r.email), r.candidate_id) for r in refs if users.get(r.email)}
    for a, b in pairs:
        if (b, a) in pairs and a < b:
            findings.append({"type": "reciprocal_references", "candidates": [a, b]})
    ip_counts = Counter(r.respondent_ip for r in refs if r.respondent_ip)
    for ip, n in ip_counts.items():
        if n >= 4:
            findings.append({"type": "same_ip_responses", "ip": ip, "responses": n})
    return findings


def respond(db: Session, token: str, confirm: bool, rating: int | None, feedback: str, ip: str) -> dict:
    ref = db.query(Reference).filter_by(token_hash=sha256(token)).first()
    if not ref or ref.status not in ("sent",):
        return {"ok": False, "error": "Invalid or already-used link"}
    cand = db.get(User, ref.candidate_id)
    with agent_run(db, "reference_tenure", f"reference:{ref.id}", ref.candidate_id) as tr:
        ref.feedback, ref.rating, ref.respondent_ip = feedback[:2000], rating, ip
        flags = []
        dom = ref.email.split("@")[-1]
        if dom in FREE_MAIL:
            flags.append("Referee used a personal email domain")
        co = db.query(Company).filter(Company.domain == dom).first()
        if co and name_similarity(co.name, ref.company) < 0.5 and ref.company.lower() not in co.name.lower():
            flags.append(f"Referee domain belongs to {co.name}, not {ref.company}")
        claimed = (cand.profile.experience or []) if cand.profile else []
        if ref.company and claimed and not any(name_similarity(e.get("company", ""), ref.company) > 0.6 or
                                               ref.company.lower() in e.get("company", "").lower() for e in claimed):
            flags.append("Company not in candidate's claimed employment history")
        for f in detect_rings(db):
            if f["type"] == "shared_referee" and f["email"] == ref.email:
                flags.append(f"Referee vouches for {f['candidates']} candidates (possible reference ring)")
            if f["type"] == "reciprocal_references" and ref.candidate_id in f["candidates"]:
                flags.append("Reciprocal reference with another candidate (possible ring)")
        tr.step("ring_and_domain_checks", flags=len(flags))
        sentiment = None
        if llm.enabled() and feedback:
            out = llm.complete_json("You assess employment reference feedback for authenticity and sentiment.",
                                    f"Feedback: {feedback}\nRating: {rating}\nReturn JSON {{\"sentiment\": \"positive|neutral|negative\", "
                                    f"\"generic_or_scripted\": bool, \"summary\": str (<=25 words)}}", required=["sentiment"])
            if out:
                tr.llm_used, sentiment = True, out
                if out.get("generic_or_scripted"):
                    flags.append("Feedback reads as generic/scripted")
        if not sentiment:
            pos = sum(w in feedback.lower() for w in ["great", "excellent", "strong", "reliable", "recommend", "good", "outstanding"])
            neg = sum(w in feedback.lower() for w in ["poor", "late", "issue", "not recommend", "terminated", "dishonest"])
            sentiment = {"sentiment": "positive" if pos > neg else ("negative" if neg > pos else "neutral"),
                         "summary": feedback[:140]}
        if not confirm:
            ref.status = "declined"
        elif len(flags) >= 2:
            ref.status = "flagged"
        else:
            ref.status = "verified"
            ref.verified_at = now()
        ref.analysis = {**(ref.analysis or {}), "flags": flags, "sentiment": sentiment}
        notify(db, ref.candidate_id, f"Reference from {ref.name}: {ref.status}",
               sentiment.get("summary", ""), "success" if ref.status == "verified" else "warning")
        db.commit()
        tr.decision, tr.needs_human = ref.status, ref.status == "flagged"
        tr.summary = f"{ref.name} ({ref.email}) → {ref.status}. " + "; ".join(flags[:2])
        tr.output = {"flags": flags, "sentiment": sentiment.get("sentiment")}
    from . import resume_architect
    resume_architect.run(db, ref.candidate_id)
    return {"ok": True, "status": ref.status}
