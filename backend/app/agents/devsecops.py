"""Agent 7 — Self-Healing DevSecOps & FinOps Agent (replaces cloud SRE & security analysts).

* Request middleware feeds a rolling latency/error window and per-actor rate counters.
* Blocks scrapers in real time (too many requests or too many distinct candidate profiles viewed).
* Periodic patrol: latency SLOs, vector index health (self-heals missing vectors), expires consent
  grants, verifies the audit hash chain, recommends scaling, tracks LLM spend.
* Rotates the vault master key (re-wraps every data key; ciphertext untouched).
"""
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from sqlalchemy.orm import Session

from ..core import ledger, vault
from ..core.config import settings
from ..models import AccessGrant, CandidateProfile, Document, SecurityBlock, User, now
from ..services import llm
from ..services.embeddings import index
from .base import agent_run


class Telemetry:
    def __init__(self):
        self.lock = threading.Lock()
        self.window = deque(maxlen=5000)  # (ts, path, ms, status)
        self.per_actor = defaultdict(lambda: deque(maxlen=2000))
        self.profile_views = defaultdict(lambda: deque(maxlen=500))  # actor -> (ts, candidate_id)
        self.blocked: dict[str, float] = {}
        self.started = time.time()

    def record(self, actor: str, path: str, ms: float, status: int):
        t = time.time()
        with self.lock:
            self.window.append((t, path, ms, status))
            self.per_actor[actor].append(t)

    def rate(self, actor: str, seconds: int = 60) -> int:
        cutoff = time.time() - seconds
        with self.lock:
            return sum(1 for t in self.per_actor[actor] if t >= cutoff)

    def is_blocked(self, actor: str) -> bool:
        until = self.blocked.get(actor)
        if until and until > time.time():
            return True
        self.blocked.pop(actor, None)
        return False

    def view_profile(self, actor: str, candidate_id: str) -> int:
        t = time.time()
        with self.lock:
            self.profile_views[actor].append((t, candidate_id))
            return len({c for ts, c in self.profile_views[actor] if ts >= t - 60})

    def stats(self) -> dict:
        cutoff = time.time() - 300
        with self.lock:
            rows = [r for r in self.window if r[0] >= cutoff]
        if not rows:
            return {"requests_5m": 0, "p50_ms": 0, "p95_ms": 0, "error_rate": 0, "rpm": 0, "slow_routes": []}
        lat = sorted(r[2] for r in rows)
        p = lambda q: round(lat[min(len(lat) - 1, int(q * len(lat)))], 1)
        errs = sum(1 for r in rows if r[3] >= 500)
        by_path = defaultdict(list)
        for r in rows:
            by_path[r[1]].append(r[2])
        slow = sorted(((k, round(sum(v) / len(v), 1)) for k, v in by_path.items()), key=lambda x: -x[1])[:5]
        span = max(1.0, time.time() - max(cutoff, self.started)) / 60
        return {"requests_5m": len(rows), "p50_ms": p(0.5), "p95_ms": p(0.95), "error_rate": round(errs / len(rows), 4),
                "rpm": round(len(rows) / span, 1), "slow_routes": [{"route": k, "avg_ms": v} for k, v in slow]}


TELEMETRY = Telemetry()
LLM_COST = {"calls": 0}


def block(db: Session, actor: str, reason: str, minutes: int = 15):
    TELEMETRY.blocked[actor] = time.time() + minutes * 60
    db.add(SecurityBlock(key=actor, reason=reason, until=now() + timedelta(minutes=minutes)))
    with agent_run(db, "devsecops_finops", actor) as tr:
        tr.decision, tr.summary = "block", f"Blocked {actor} for {minutes} min: {reason}"
        tr.output = {"actor": actor, "reason": reason}
    db.commit()


def check_scrape(db: Session, actor: str, candidate_id: str) -> bool:
    """Returns True if the actor should be blocked for scraping candidate profiles."""
    distinct = TELEMETRY.view_profile(actor, candidate_id)
    if distinct > settings.SCRAPE_PROFILE_VIEWS_PER_MIN:
        block(db, actor, f"Viewed {distinct} distinct candidate profiles in 60s (scraping pattern)")
        return True
    return False


def rotate_keys(db: Session) -> dict:
    with agent_run(db, "devsecops_finops", "vault:kek") as tr:
        old_versions = vault.kek_versions()
        new_ver = f"v{len(old_versions) + 1}"
        vault.add_kek(new_ver)
        n = 0
        for d in db.query(Document).all():
            if d.kek_version != new_ver:
                d.wrapped_dek = vault.rewrap(d.wrapped_dek, d.kek_version, new_ver)
                d.kek_version = new_ver
                n += 1
        for p in db.query(CandidateProfile).filter(CandidateProfile.pan_sealed != "").all():
            p.pan_sealed = vault.reseal_field(p.pan_sealed, new_ver)
            n += 1
        db.commit()
        tr.decision, tr.summary = "rotated", f"Rotated KEK to {new_ver}; re-wrapped {n} data keys (ciphertext untouched)"
        tr.output = {"new_version": new_ver, "rewrapped": n}
    return {"active_kek": new_ver, "rewrapped": n}


def patrol(db: Session) -> dict:
    with agent_run(db, "devsecops_finops", "platform:patrol") as tr:
        st = TELEMETRY.stats()
        actions = []
        # 1. Vector index self-heal
        profs = db.query(CandidateProfile).all()
        idx = index()
        missing = 0
        if idx.size() < len(profs):
            from .resume_architect import profile_text
            from ..services.embeddings import embed
            for p in profs:
                if not p.embedding:
                    p.embedding = embed(profile_text(db.get(User, p.user_id), p))
                idx.upsert(p.user_id, p.embedding)
                missing += 1
            db.commit()
            actions.append(f"Re-indexed {missing} candidate vectors")
        # 2. Consent expiry
        expired = db.query(AccessGrant).filter(AccessGrant.status == "granted", AccessGrant.expires_at < now()).all()
        for g in expired:
            g.status = "expired"
            ledger.record(db, "agent:devsecops_finops", "consent.expire", actor_type="agent", subject_id=g.candidate_id,
                          target=f"grant:{g.id}", commit=False)
        if expired:
            db.commit(); actions.append(f"Expired {len(expired)} time-bound consent grants")
        # 3. Ledger integrity
        chain = ledger.verify_chain(db)
        if not chain["valid"]:
            tr.needs_human = True
            actions.append(f"ALERT: audit chain broken at seq {chain['broken_at_seq']}")
        # 4. SLOs & scaling recommendation
        scale = "hold"
        if st["p95_ms"] > 800 or st["rpm"] > 600:
            scale = "scale_out"
            actions.append(f"p95 {st['p95_ms']} ms / {st['rpm']} rpm above SLO → recommend +1 instance")
        elif st["rpm"] < 5 and st["requests_5m"] > 0:
            scale = "scale_in_candidate"
        # 5. Key age policy (rotate if no rotation logged in 30 days — demo uses on-demand)
        active_blocks = {k: round(v - time.time()) for k, v in TELEMETRY.blocked.items() if v > time.time()}
        finops = {"llm_provider": llm.provider(), "est_llm_calls": LLM_COST["calls"],
                  "infra": "1× web (Render) + managed Postgres", "est_monthly_usd": 7 + 0.002 * LLM_COST["calls"] * 30}
        report = {"telemetry": st, "vector_index": {"backend": idx.backend, "size": idx.size(), "profiles": len(profs)},
                  "ledger": chain, "scaling": scale, "blocked_actors": active_blocks, "actions": actions,
                  "kek_versions": vault.kek_versions(), "finops": finops}
        tr.decision = "healthy" if chain["valid"] and st["p95_ms"] < 800 else "degraded"
        tr.summary = f"p95 {st['p95_ms']} ms, {st['requests_5m']} req/5m, index {idx.size()}/{len(profs)}. " + ("; ".join(actions) or "No action needed.")
        tr.output = {"scaling": scale, "actions": actions}
    return report


def patrol_loop(session_factory, interval: int = 120):
    def loop():
        while True:
            time.sleep(interval)
            try:
                db = session_factory()
                try:
                    patrol(db)
                finally:
                    db.close()
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="devsecops-patrol").start()
