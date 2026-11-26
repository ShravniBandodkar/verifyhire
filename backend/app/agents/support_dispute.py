"""Agent 6 — Autonomous Support & Dispute Agent (replaces customer support & trust officers).

LangGraph: understand → (tool) act → respond. Tool calls are deterministic, schema-checked and
scoped to the caller's own records (guardrail: the agent can never act on another user's data).
Anything outside its tools escalates to the human governor queue.
"""
import re
from datetime import timedelta
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from ..core import ledger
from ..models import AccessGrant, CandidateProfile, Company, Document, Job, Match, SupportMessage, User, now
from ..services import llm
from .base import agent_run

TOOLS = {
    "trust_status": "Explain the user's Trust Score and what is missing",
    "list_access": "List employer access requests/grants for the candidate",
    "revoke_access": "Revoke an employer's access (arg: company name)",
    "extend_access": "Extend an active grant by N days (args: company, days)",
    "retry_kyc": "Re-run verification on a flagged/rejected document (arg: doc type)",
    "update_profile": "Correct a profile field (args: field in [city, phone, headline, expected_ctc_lpa], value)",
    "kyb_status": "Explain the employer's KYB status and failed checks",
    "job_pipeline": "Summarise the employer's open jobs and matches",
    "escalate": "Escalate to a human governor (dispute the agent cannot resolve)",
    "faq": "Answer a general platform question",
}

FAQ = {
    "aadhaar": "We never store your Aadhaar number — only a masked form (XXXX-XXXX-1234) and an irreversible token from OTP e-KYC.",
    "privacy": "Employers only see documents you approve, for the time window you choose. Every view is watermarked and logged in your audit trail.",
    "delete": "Under the DPDP Act you can request erasure; I can escalate an erasure request to the data protection governor.",
    "trust": "Your Trust Score is verification completeness: Aadhaar 20, PAN 15, degree 15, selfie 10, resume 10, employment 10, CTC proof 10, references 10.",
    "api": "Developers can create API keys under Developers and call the REST API documented at /docs.",
}


class SupState(TypedDict, total=False):
    ctx: Any
    user: Any
    message: str
    intent: str
    args: dict
    result: Any
    reply: str


def rule_intent(msg: str, role: str) -> tuple[str, dict]:
    m = msg.lower()
    co = re.search(r"(?:from|for|of|to)\s+([A-Z][\w&.]*(?:\s+[A-Z][\w&.]*)*)", msg)
    company = co.group(1) if co else ""
    if re.search(r"\b(revoke|remove|withdraw|cancel)\b.*\b(access|consent|permission)\b|\bstop\b.*\bseeing\b", m):
        return "revoke_access", {"company": company}
    if re.search(r"\bextend\b", m):
        d = re.search(r"(\d+)\s*day", m)
        return "extend_access", {"company": company, "days": int(d.group(1)) if d else 7}
    if re.search(r"\b(retry|re-?run|re-?verify|again)\b", m):
        for t in ["aadhaar", "pan", "degree", "payslip", "experience", "resume"]:
            if t in m:
                return "retry_kyc", {"doc_type": "experience_letter" if t == "experience" else t}
        return "retry_kyc", {"doc_type": ""}
    up = re.search(r"\b(?:change|update|correct|set)\b\s+(?:my\s+)?(city|phone|headline|expected ctc)\s+(?:to\s+)?(.+)", msg, re.I)
    if up:
        field = "expected_ctc_lpa" if "ctc" in up.group(1).lower() else up.group(1).lower()
        return "update_profile", {"field": field, "value": up.group(2).strip().rstrip(".")}
    if re.search(r"\b(who|which)\b.*\b(view|saw|seen|access)|access requests?|grants?\b", m):
        return "list_access", {}
    if re.search(r"\b(dispute|wrong|unfair|complain|human|appeal|fraud)\b", m):
        return "escalate", {"reason": msg}
    if role != "candidate" and re.search(r"\bkyb\b|verification status|why.*(flag|reject)", m):
        return "kyb_status", {}
    if role != "candidate" and re.search(r"\b(jobs?|pipeline|matches|shortlist)\b", m):
        return "job_pipeline", {}
    if re.search(r"trust|score|missing|complete|verify|verification", m):
        return "trust_status" if role == "candidate" else "kyb_status", {}
    return "faq", {"topic": next((k for k in FAQ if k in m), "")}


def n_understand(s: SupState):
    tr, u = s["ctx"]["trace"], s["user"]
    intent, args = rule_intent(s["message"], u.role)
    if llm.enabled():
        out = llm.complete_json(
            "You are the support router for VerifyHire, an Indian verified-resume platform. Pick exactly one tool.",
            f"User role: {u.role}. Tools: {TOOLS}. Message: {s['message']}\n"
            "Return JSON {\"tool\": one of the tool names, \"args\": {...}}", required=["tool"])
        if out and out.get("tool") in TOOLS:
            tr.llm_used = True
            intent, args = out["tool"], {**args, **(out.get("args") or {})}
    s["intent"], s["args"] = intent, args
    tr.step("understand", intent=intent, args=args)
    return s


def _find_company(db: Session, name: str):
    if not name:
        return None
    return db.query(Company).filter(Company.name.ilike(f"%{name.strip()}%")).first()


def n_act(s: SupState):
    db: Session = s["ctx"]["db"]
    u, a, intent = s["user"], s["args"], s["intent"]
    r: Any = None
    if intent == "trust_status" and u.role == "candidate":
        from .resume_architect import run as arch
        out = arch(db, u.id)
        r = {"score": out.get("trust_score"), "gaps": out.get("gaps", [])[:3]}
    elif intent == "list_access" and u.role == "candidate":
        gs = db.query(AccessGrant).filter_by(candidate_id=u.id).order_by(AccessGrant.created_at.desc()).limit(10).all()
        r = [{"company": g.company.name, "status": g.status, "docs": g.doc_types,
              "expires": g.expires_at.isoformat() if g.expires_at else None} for g in gs]
    elif intent in ("revoke_access", "extend_access") and u.role == "candidate":
        co = _find_company(db, a.get("company", ""))
        q = db.query(AccessGrant).filter_by(candidate_id=u.id, status="granted")
        if co:
            q = q.filter_by(company_id=co.id)
        gs = q.all()
        if not gs:
            r = {"changed": 0, "company": co.name if co else a.get("company")}
        else:
            for g in gs:
                if intent == "revoke_access":
                    g.status = "revoked"; g.decided_at = now()
                else:
                    g.expires_at = (g.expires_at or now()) + timedelta(days=int(a.get("days", 7)))
                ledger.record(db, "agent:support_dispute", f"consent.{'revoke' if intent == 'revoke_access' else 'extend'}",
                              actor_type="agent", subject_id=u.id, target=f"grant:{g.id}",
                              details={"company": g.company.name, "on_behalf_of": u.id}, commit=False)
            db.commit()
            r = {"changed": len(gs), "company": gs[0].company.name}
    elif intent == "retry_kyc" and u.role == "candidate":
        q = db.query(Document).filter(Document.owner_id == u.id, Document.status.in_(["flagged", "rejected"]))
        if a.get("doc_type"):
            q = q.filter(Document.doc_type == a["doc_type"])
        docs = q.all()
        from . import orchestrator
        r = [orchestrator.process_document(db, d.id) for d in docs]
    elif intent == "update_profile" and u.role == "candidate":
        prof = db.get(CandidateProfile, u.id)
        field, val = a.get("field"), a.get("value", "")
        if field in ("city", "phone", "headline"):
            setattr(prof, field, str(val)[:120]); db.commit(); r = {"field": field, "value": val}
        elif field == "expected_ctc_lpa":
            num = re.search(r"\d+(?:\.\d+)?", str(val))
            if num:
                prof.expected_ctc_lpa = float(num.group(0)); db.commit(); r = {"field": field, "value": prof.expected_ctc_lpa}
        if r:
            ledger.record(db, "agent:support_dispute", "profile.correct", actor_type="agent", subject_id=u.id,
                          target=f"profile:{field}", details={"value": str(val)[:60]})
    elif intent == "kyb_status" and u.company_id:
        co = db.get(Company, u.company_id)
        failed = [c["check"] for c in (co.kyb_report or {}).get("checks", []) if not c["ok"]]
        r = {"status": co.kyb_status, "risk": co.risk_score, "failed": failed}
    elif intent == "job_pipeline" and u.company_id:
        jobs = db.query(Job).filter_by(company_id=u.company_id).all()
        r = [{"title": j.title, "matches": db.query(Match).filter_by(job_id=j.id).count(),
              "shortlisted": db.query(Match).filter_by(job_id=j.id, status="shortlisted").count()} for j in jobs]
    elif intent == "escalate":
        s["ctx"]["trace"].needs_human = True
        r = {"ticket": f"GOV-{now().strftime('%y%m%d%H%M%S')}"}
    else:
        r = FAQ.get(a.get("topic") or "", None)
    s["result"] = r
    s["ctx"]["trace"].step("act", tool=s["intent"])
    return s


def template_reply(intent: str, r: Any, role: str) -> str:
    if intent == "trust_status" and r:
        gaps = "; ".join(f"{g['label']} (+{g['points']}): {g['action']}" for g in r["gaps"]) or "nothing — you're at 100!"
        return f"Your Trust Score is {r['score']}/100. To raise it: {gaps}"
    if intent == "list_access":
        if not r:
            return "No employer has requested access to your vault yet."
        return "Here are your recent access requests:\n" + "\n".join(
            f"• {g['company']}: {g['status']}" + (f" (expires {g['expires'][:10]})" if g["expires"] else "") for g in r)
    if intent == "revoke_access":
        return (f"Done — I revoked {r['changed']} active grant(s) for {r['company']}. They can no longer open your documents, and this is recorded in your audit log."
                if r and r["changed"] else f"I couldn't find an active grant{(' for ' + str(r['company'])) if r and r.get('company') else ''}. Ask me 'who has access?' to see them.")
    if intent == "extend_access":
        return f"Extended {r['changed']} grant(s) for {r['company']}." if r and r["changed"] else "No active grant found to extend."
    if intent == "retry_kyc":
        if not r:
            return "You have no flagged or rejected documents — nothing to retry."
        return "I re-ran verification: " + "; ".join(f"{x.get('doc_type')} → {x.get('verdict')}" for x in r if x)
    if intent == "update_profile":
        return f"Updated your {r['field']} to {r['value']}." if r else "I couldn't apply that change — try e.g. 'change my city to Pune'."
    if intent == "kyb_status" and r:
        return f"Your company KYB status is {r['status']} (risk {r['risk']}/100)." + (
            f" Checks that need attention: {', '.join(r['failed'])}." if r["failed"] else " All checks passed.")
    if intent == "job_pipeline":
        return "\n".join(f"• {j['title']}: {j['matches']} AI matches, {j['shortlisted']} shortlisted" for j in r or []) or "No jobs yet — post one from the Jobs tab."
    if intent == "escalate":
        return f"I've opened governor ticket {r['ticket']}. A human governor reviews disputes the agents can't resolve; you'll be notified here."
    if isinstance(r, str):
        return r
    return ("I can help with your Trust Score, access requests (grant/revoke/extend), re-running KYC, profile corrections, "
            "KYB status and job pipelines. What would you like to do?")


def n_respond(s: SupState):
    reply = template_reply(s["intent"], s["result"], s["user"].role)
    if llm.enabled() and s["intent"] in ("faq",):
        t = llm.complete("You are VerifyHire's friendly support agent. Be concise (<=80 words). Only state facts about "
                         "VerifyHire given here: " + str(FAQ), s["message"])
        if t:
            s["ctx"]["trace"].llm_used, reply = True, t.strip()
    s["reply"] = reply
    return s


def _build():
    g = StateGraph(SupState)
    g.add_node("understand", n_understand)
    g.add_node("act", n_act)
    g.add_node("respond", n_respond)
    g.set_entry_point("understand")
    g.add_edge("understand", "act")
    g.add_edge("act", "respond")
    g.add_edge("respond", END)
    return g.compile()


GRAPH = _build()


def chat(db: Session, user: User, message: str) -> dict:
    db.add(SupportMessage(user_id=user.id, role="user", content=message[:4000]))
    db.commit()
    with agent_run(db, "support_dispute", f"user:{user.id}", user.id) as tr:
        out = GRAPH.invoke({"ctx": {"db": db, "trace": tr}, "user": user, "message": message})
        tr.decision, tr.summary = out["intent"], out["reply"][:300]
        tr.output = {"intent": out["intent"]}
    db.add(SupportMessage(user_id=user.id, role="agent", content=out["reply"],
                          tool_calls=[{"tool": out["intent"], "args": out["args"]}]))
    db.commit()
    return {"reply": out["reply"], "tool": out["intent"], "args": out["args"]}
