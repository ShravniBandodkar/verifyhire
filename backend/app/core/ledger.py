"""Immutable, append-only audit ledger.

Each event stores sha256(prev_hash + canonical(event)). Altering or deleting any historical row
breaks every hash after it, which `verify_chain` detects.
"""
import hashlib
import json
import threading

from sqlalchemy.orm import Session

GENESIS = "0" * 64
_lock = threading.Lock()


def _digest(prev: str, ev: dict) -> str:
    canonical = json.dumps(ev, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256((prev + canonical).encode()).hexdigest()


def _payload(e) -> dict:
    return {
        "ts": e.ts.isoformat(), "actor_id": e.actor_id, "actor_type": e.actor_type,
        "action": e.action, "subject_id": e.subject_id or "", "target": e.target or "",
        "details": e.details or {},
    }


def record(db: Session, actor_id: str, action: str, *, actor_type: str = "user",
           subject_id: str = "", target: str = "", details: dict | None = None, commit: bool = True):
    from ..models import AuditEvent, now

    with _lock:
        last = db.query(AuditEvent).order_by(AuditEvent.seq.desc()).first()
        prev = last.hash if last else GENESIS
        ev = AuditEvent(ts=now().replace(microsecond=0), actor_id=actor_id, actor_type=actor_type,
                        action=action, subject_id=subject_id, target=target,
                        details=details or {}, prev_hash=prev, hash="")
        ev.hash = _digest(prev, _payload(ev))
        db.add(ev)
        if commit:
            db.commit()
        else:
            db.flush()
    return ev


def verify_chain(db: Session) -> dict:
    from ..models import AuditEvent

    prev = GENESIS
    count = 0
    for e in db.query(AuditEvent).order_by(AuditEvent.seq.asc()).yield_per(500):
        if e.prev_hash != prev or _digest(prev, _payload(e)) != e.hash:
            return {"valid": False, "broken_at_seq": e.seq, "checked": count}
        prev = e.hash
        count += 1
    return {"valid": True, "checked": count, "head": prev}
