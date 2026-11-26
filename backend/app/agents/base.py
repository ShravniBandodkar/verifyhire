"""Shared agent runtime: every agent decision is timed, persisted as an AgentRun (for the human
governor console) and written to the immutable ledger."""
import hashlib
import hmac
import base64
import json
import time
from contextlib import contextmanager

from sqlalchemy.orm import Session

from ..core import ledger
from ..core.config import settings
from ..models import AgentRun, Notification

AGENTS = {
    "kyc_forensics": {"name": "KYC & Document Forensics Agent", "replaces": "KYC / BGV Verification Analyst"},
    "kyb_underwriting": {"name": "Corporate KYB Underwriting Agent", "replaces": "B2B Merchant Onboarding Specialist"},
    "reference_tenure": {"name": "Autonomous Reference & Tenure Agent", "replaces": "Background Check & Reference Caller"},
    "talent_matchmaker": {"name": "Semantic Talent Matchmaker Agent", "replaces": "Technical Sourcer & Recruiter"},
    "resume_architect": {"name": "Career & Resume Architect Agent", "replaces": "Resume Writer & Career Coach"},
    "support_dispute": {"name": "Autonomous Support & Dispute Agent", "replaces": "Customer Support & Trust Officer"},
    "devsecops_finops": {"name": "Self-Healing DevSecOps & FinOps Agent", "replaces": "Cloud SRE & Security Analyst"},
}


class RunTrace:
    def __init__(self, agent: str, subject: str):
        self.agent, self.subject = agent, subject
        self.steps: list[dict] = []
        self.llm_used = False
        self.decision = ""
        self.summary = ""
        self.output: dict = {}
        self.needs_human = False
        self.t0 = time.perf_counter()

    def step(self, name: str, **info):
        self.steps.append({"step": name, "t_ms": int((time.perf_counter() - self.t0) * 1000), **info})


@contextmanager
def agent_run(db: Session, agent: str, subject: str, subject_user: str = ""):
    tr = RunTrace(agent, subject)
    try:
        yield tr
    finally:
        dur = int((time.perf_counter() - tr.t0) * 1000)
        db.add(AgentRun(agent=agent, subject=subject, decision=tr.decision, summary=tr.summary[:2000],
                        output=tr.output, steps=tr.steps, llm_used=tr.llm_used,
                        needs_human=tr.needs_human, duration_ms=dur))
        ledger.record(db, f"agent:{agent}", f"agent.{agent}.decision", actor_type="agent",
                      subject_id=subject_user, target=subject,
                      details={"decision": tr.decision, "summary": tr.summary[:300], "llm": tr.llm_used,
                               "duration_ms": dur})


def notify(db: Session, user_id: str, title: str, body: str = "", kind: str = "info"):
    db.add(Notification(user_id=user_id, title=title, body=body, kind=kind))


def sign_badge(payload: dict) -> str:
    """Tamper-evident verification badge: base64(payload).HMAC-SHA256 signature."""
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")
    sig = hmac.new(settings.BADGE_SIGNING_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_badge(token: str) -> dict | None:
    try:
        body, sig = token.rsplit(".", 1)
        exp = hmac.new(settings.BADGE_SIGNING_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, exp):
            return None
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None
