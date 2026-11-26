"""Agent orchestrator — the event bus that wires the seven agents into autonomous workflows.

Platform supervisor graph (LangGraph), triggered for every new document:

    KYC Forensics ──► Resume Architect ──► Talent Matchmaker
          │ (rejected → stop; flagged → governor queue)

Other events: company.registered → KYB Underwriting; job.created → Matchmaker;
reference.responded → Reference agent → Architect; periodic → DevSecOps patrol.
"""
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from . import kyb_underwriting, kyc_forensics, resume_architect, talent_matchmaker


class PipeState(TypedDict, total=False):
    db: Any
    doc_id: str
    owner_id: str
    kyc: dict
    trust: dict
    matched_jobs: int


def p_kyc(s: PipeState):
    s["kyc"] = kyc_forensics.run(s["db"], s["doc_id"])
    return s


def route_after_kyc(s: PipeState) -> str:
    return "stop" if s["kyc"].get("verdict") == "rejected" or s["kyc"].get("error") else "architect"


def p_architect(s: PipeState):
    s["trust"] = resume_architect.run(s["db"], s["owner_id"])
    return s


def p_match(s: PipeState):
    db: Session = s["db"]
    from ..models import Job
    jobs = db.query(Job).filter_by(status="open").all()
    for j in jobs:
        talent_matchmaker.match_job(db, j.id)
    s["matched_jobs"] = len(jobs)
    return s


def _build():
    g = StateGraph(PipeState)
    g.add_node("kyc_forensics", p_kyc)
    g.add_node("architect", p_architect)
    g.add_node("matchmaker", p_match)
    g.set_entry_point("kyc_forensics")
    g.add_conditional_edges("kyc_forensics", route_after_kyc, {"architect": "architect", "stop": END})
    g.add_edge("architect", "matchmaker")
    g.add_edge("matchmaker", END)
    return g.compile()


PIPELINE = _build()


def process_document(db: Session, doc_id: str, rematch: bool = False) -> dict:
    from ..models import Document
    d = db.get(Document, doc_id)
    out = PIPELINE.invoke({"db": db, "doc_id": doc_id, "owner_id": d.owner_id})
    return {"doc_id": doc_id, **(out.get("kyc") or {}), "trust_score": (out.get("trust") or {}).get("trust_score")}


# ---- background helpers (own DB session, safe for FastAPI BackgroundTasks) ----
def bg(fn, *args):
    db = SessionLocal()
    try:
        return fn(db, *args)
    finally:
        db.close()


def bg_process_document(doc_id: str):
    bg(process_document, doc_id)


def bg_kyb(company_id: str):
    bg(kyb_underwriting.run, company_id)


def bg_match_job(job_id: str):
    bg(talent_matchmaker.match_job, job_id)


def bg_architect(user_id: str):
    bg(resume_architect.run, user_id)


def bg_rematch_all():
    bg(talent_matchmaker.rematch_all)
