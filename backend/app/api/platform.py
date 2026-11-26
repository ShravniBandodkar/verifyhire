"""Shared endpoints: notifications, support agent, public reference flow, badge verification,
developer API keys and the admin / human-governor console."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..agents import devsecops, kyb_underwriting, orchestrator, reference_tenure, support_dispute
from ..agents.base import AGENTS, verify_badge
from ..core import ledger, vault
from ..core.db import get_db
from ..core.security import get_current_user, new_api_key, require_roles
from ..models import (AgentRun, ApiKey, AuditEvent, CandidateProfile, Company, Document, Job, Match, Notification,
                      Reference, SecurityBlock, SupportMessage, User)
from ..services import llm
from ..services.embeddings import index

router = APIRouter(tags=["Platform"])
admin = require_roles("admin")


# ---------- Notifications ----------
@router.get("/notifications", summary="Notifications (polled by web, desktop tray and mobile push)")
def notifications(unread_only: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Notification).filter_by(user_id=user.id)
    if unread_only:
        q = q.filter_by(read=False)
    return [{"id": n.id, "title": n.title, "body": n.body, "kind": n.kind, "read": n.read, "ts": n.ts.isoformat()}
            for n in q.order_by(Notification.ts.desc()).limit(50)]


@router.post("/notifications/read", summary="Mark all notifications read")
def mark_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter_by(user_id=user.id, read=False).update({"read": True})
    db.commit()
    return {"ok": True}


# ---------- Support agent ----------
class ChatIn(BaseModel):
    message: str


@router.post("/support/chat", tags=["Support Agent"], summary="Chat with the autonomous Support & Dispute agent")
def chat(body: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return support_dispute.chat(db, user, body.message)


@router.get("/support/history", tags=["Support Agent"], summary="Support conversation history")
def history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"role": m.role, "content": m.content, "tool_calls": m.tool_calls, "ts": m.ts.isoformat()}
            for m in db.query(SupportMessage).filter_by(user_id=user.id).order_by(SupportMessage.ts.asc()).limit(100)]


# ---------- Public: reference verification & badges ----------
@router.get("/public/reference/{token}", tags=["Public"], summary="Reference verification form data")
def reference_form(token: str, db: Session = Depends(get_db)):
    from ..core.security import sha256
    r = db.query(Reference).filter_by(token_hash=sha256(token)).first()
    if not r:
        raise HTTPException(404, "Invalid link")
    cand = db.get(User, r.candidate_id)
    return {"referee": r.name, "candidate": cand.full_name, "company": r.company, "relationship": r.relationship_,
            "status": r.status, "questions": reference_tenure.QUESTIONS}


class RefResponse(BaseModel):
    confirm: bool
    rating: int | None = None
    feedback: str = ""


@router.post("/public/reference/{token}", tags=["Public"], summary="Submit reference verification")
def reference_submit(token: str, body: RefResponse, request: Request, db: Session = Depends(get_db)):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0]
    out = reference_tenure.respond(db, token, body.confirm, body.rating, body.feedback, ip)
    if not out["ok"]:
        raise HTTPException(400, out["error"])
    return out


class BadgeIn(BaseModel):
    badge: str


@router.post("/public/badges/verify", tags=["Public"], summary="Verify a tamper-proof verification badge")
def badge_verify(body: BadgeIn, db: Session = Depends(get_db)):
    data = verify_badge(body.badge)
    if not data:
        return {"valid": False}
    d = db.get(Document, data["doc_id"])
    return {"valid": True, "payload": data, "document_still_matches": bool(d and d.sha256 == data["sha256"] and d.status == "verified")}


@router.get("/public/stats", tags=["Public"], summary="Platform statistics")
def stats(db: Session = Depends(get_db)):
    total_runs = db.query(AgentRun).count()
    human = db.query(AgentRun).filter_by(needs_human=True).count()
    return {"candidates": db.query(User).filter_by(role="candidate").count(),
            "verified_employers": db.query(Company).filter_by(kyb_status="approved").count(),
            "documents_verified": db.query(Document).filter_by(status="verified").count(),
            "open_jobs": db.query(Job).filter_by(status="open").count(),
            "agent_decisions": total_runs,
            "autonomy_rate": round(100 * (1 - human / total_runs), 1) if total_runs else 100.0,
            "agents": len(AGENTS), "llm_provider": llm.provider(), "vector_backend": index().backend}


# ---------- Developer API keys ----------
class KeyIn(BaseModel):
    name: str


@router.post("/developer/keys", tags=["Developer"], summary="Create an API key (send as X-API-Key header)")
def create_key(body: KeyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    raw, prefix, h = new_api_key()
    k = ApiKey(user_id=user.id, name=body.name[:120], prefix=prefix, key_hash=h)
    db.add(k); db.commit()
    ledger.record(db, user.id, "apikey.create", target=f"apikey:{k.id}", details={"prefix": prefix})
    return {"id": k.id, "name": k.name, "key": raw, "prefix": prefix, "note": "Shown once — store it securely."}


@router.get("/developer/keys", tags=["Developer"], summary="List my API keys")
def list_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": k.id, "name": k.name, "prefix": k.prefix, "revoked": k.revoked,
             "last_used": k.last_used.isoformat() if k.last_used else None, "created_at": k.created_at.isoformat()}
            for k in db.query(ApiKey).filter_by(user_id=user.id)]


@router.delete("/developer/keys/{kid}", tags=["Developer"], summary="Revoke an API key")
def revoke_key(kid: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    k = db.get(ApiKey, kid)
    if not k or k.user_id != user.id:
        raise HTTPException(404)
    k.revoked = True; db.commit()
    ledger.record(db, user.id, "apikey.revoke", target=f"apikey:{k.id}")
    return {"ok": True}


# ---------- Admin / Human governor console ----------
@router.get("/admin/agents", tags=["Governor"], summary="Agent workforce overview")
def agents(user: User = Depends(admin), db: Session = Depends(get_db)):
    rows = db.query(AgentRun.agent, func.count(), func.avg(AgentRun.duration_ms), func.sum(AgentRun.needs_human.cast(int_type()))).group_by(AgentRun.agent).all()
    stats = {r[0]: {"runs": r[1], "avg_ms": round(r[2] or 0), "escalations": int(r[3] or 0)} for r in rows}
    return [{"key": k, **v, **stats.get(k, {"runs": 0, "avg_ms": 0, "escalations": 0})} for k, v in AGENTS.items()]


def int_type():
    from sqlalchemy import Integer
    return Integer


@router.get("/admin/runs", tags=["Governor"], summary="Agent decision log")
def runs(agent: str | None = None, needs_human: bool | None = None, limit: int = 100,
         user: User = Depends(admin), db: Session = Depends(get_db)):
    q = db.query(AgentRun)
    if agent:
        q = q.filter_by(agent=agent)
    if needs_human is not None:
        q = q.filter_by(needs_human=needs_human)
    return [{"id": r.id, "agent": r.agent, "subject": r.subject, "decision": r.decision, "summary": r.summary,
             "steps": r.steps, "llm_used": r.llm_used, "needs_human": r.needs_human, "duration_ms": r.duration_ms,
             "ts": r.ts.isoformat()} for r in q.order_by(AgentRun.ts.desc()).limit(min(limit, 500))]


class Override(BaseModel):
    status: str
    note: str = ""


@router.post("/admin/companies/{cid}/override", tags=["Governor"], summary="Governor override of a KYB decision")
def override_company(cid: str, body: Override, user: User = Depends(admin), db: Session = Depends(get_db)):
    co = db.get(Company, cid)
    if body.status not in ("approved", "rejected", "flagged"):
        raise HTTPException(400)
    co.kyb_status = body.status
    db.query(AgentRun).filter(AgentRun.subject == f"company:{cid}", AgentRun.needs_human == True).update({"needs_human": False})  # noqa
    db.commit()
    ledger.record(db, user.id, "governor.override", target=f"company:{cid}", details={"status": body.status, "note": body.note})
    return {"ok": True}


@router.post("/admin/documents/{did}/override", tags=["Governor"], summary="Governor override of a document decision")
def override_doc(did: str, body: Override, user: User = Depends(admin), db: Session = Depends(get_db)):
    d = db.get(Document, did)
    if body.status not in ("verified", "rejected", "flagged"):
        raise HTTPException(400)
    d.status = body.status
    db.query(AgentRun).filter(AgentRun.subject == f"document:{did}", AgentRun.needs_human == True).update({"needs_human": False})  # noqa
    db.commit()
    ledger.record(db, user.id, "governor.override", subject_id=d.owner_id, target=f"document:{did}",
                  details={"status": body.status, "note": body.note})
    return {"ok": True}


@router.post("/admin/runs/{rid}/resolve", tags=["Governor"], summary="Acknowledge an escalation")
def resolve(rid: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    r = db.get(AgentRun, rid)
    r.needs_human = False; db.commit()
    ledger.record(db, user.id, "governor.resolve", target=f"run:{rid}")
    return {"ok": True}


@router.get("/admin/companies", tags=["Governor"], summary="All companies with KYB status")
def companies(user: User = Depends(admin), db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "kyb_status": c.kyb_status, "risk_score": c.risk_score,
             "narrative": (c.kyb_report or {}).get("narrative", ""), "checks": (c.kyb_report or {}).get("checks", [])}
            for c in db.query(Company).order_by(Company.created_at.desc())]


@router.get("/admin/ledger", tags=["Governor"], summary="Immutable audit ledger (latest events)")
def ledger_list(limit: int = 100, user: User = Depends(admin), db: Session = Depends(get_db)):
    return [{"seq": e.seq, "ts": e.ts.isoformat(), "actor": e.actor_id, "actor_type": e.actor_type, "action": e.action,
             "target": e.target, "subject": e.subject_id, "hash": e.hash, "prev_hash": e.prev_hash}
            for e in db.query(AuditEvent).order_by(AuditEvent.seq.desc()).limit(min(limit, 500))]


@router.get("/admin/ledger/verify", tags=["Governor"], summary="Verify the audit hash chain end-to-end")
def ledger_verify(user: User = Depends(admin), db: Session = Depends(get_db)):
    return ledger.verify_chain(db)


@router.post("/admin/devsecops/patrol", tags=["Governor"], summary="Run the DevSecOps agent patrol now")
def patrol(user: User = Depends(admin), db: Session = Depends(get_db)):
    return devsecops.patrol(db)


@router.post("/admin/devsecops/rotate-keys", tags=["Governor"], summary="Rotate the vault master key")
def rotate(user: User = Depends(admin), db: Session = Depends(get_db)):
    return devsecops.rotate_keys(db)


@router.get("/admin/security/blocks", tags=["Governor"], summary="Security blocks issued by the agent")
def blocks(user: User = Depends(admin), db: Session = Depends(get_db)):
    return [{"key": b.key, "reason": b.reason, "until": b.until.isoformat(), "ts": b.ts.isoformat()}
            for b in db.query(SecurityBlock).order_by(SecurityBlock.ts.desc()).limit(50)]


@router.post("/admin/users/{uid}/unblock", tags=["Governor"], summary="Lift a security block")
def unblock(uid: str, user: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    u.is_blocked = False
    devsecops.TELEMETRY.blocked.pop(f"user:{uid}", None)
    db.commit()
    ledger.record(db, user.id, "governor.unblock", target=f"user:{uid}")
    return {"ok": True}
