"""Agent 4 — Semantic Talent Matchmaker Agent (replaces technical sourcers & recruiters).

* Natural-language query → structured filters (LLM when available, deterministic parser always).
* Hybrid retrieval: structured SQL pre-filter (city, experience, CTC, verification flags,
  references) → vector similarity (pgvector/NumPy) → explainable re-ranking.
* Prompt-to-JD: turns a rough employer prompt into a structured requisition.
* Proactively computes top-10 matches per open job and drafts personalised outreach.
"""
import re
import time

from sqlalchemy.orm import Session

from ..models import CandidateProfile, Company, Job, Match, Reference, User
from ..services import llm
from ..services.embeddings import embed, extract_skills, index
from .base import agent_run, notify

CITIES = ["bengaluru", "bangalore", "mumbai", "pune", "hyderabad", "chennai", "delhi", "gurugram", "gurgaon",
          "noida", "kolkata", "ahmedabad", "kochi", "jaipur", "remote"]
CITY_CANON = {"bangalore": "bengaluru", "gurgaon": "gurugram"}
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def parse_query(q: str) -> dict:
    ql = q.lower()
    f: dict = {"skills": extract_skills(q)}
    for c in CITIES:
        if re.search(rf"\b{c}\b", ql):
            f["city"] = CITY_CANON.get(c, c); break
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:\+\s*)?(?:years|yrs|yoe)", ql)
    if m:
        f["min_exp"], f["max_exp"] = float(m.group(1)), float(m.group(2))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs|yoe)", ql)
        if m:
            f["min_exp"] = float(m.group(1))
    m = re.search(r"(?:ctc|salary|package)?\s*(?:under|below|less than|<|upto|up to|max)\s*₹?\s*(\d+(?:\.\d+)?)\s*(?:lpa|l|lakhs?)", ql)
    if m:
        f["ctc_max"] = float(m.group(1))
    m = re.search(r"(?:above|over|more than|>|min)\s*₹?\s*(\d+(?:\.\d+)?)\s*(?:lpa|l|lakhs?)", ql)
    if m:
        f["ctc_min"] = float(m.group(1))
    if re.search(r"pan[- ]verified|verified pan", ql):
        f["pan_verified"] = True
    if re.search(r"aadhaar[- ]verified|kyc[- ]verified|fully verified", ql):
        f["aadhaar_verified"] = True
    if re.search(r"verified\s+(?:b\.?tech|m\.?tech|degree|b\.?e|mba|m\.?s)", ql):
        f["degree_verified"] = True
    deg = re.search(r"\b(b\.?tech|m\.?tech|b\.?e|mba|m\.?s|mca|bca|b\.?sc)\b", ql)
    if deg:
        f["degree_kw"] = deg.group(1).replace(".", "")
    m = re.search(r"(?:at least|min(?:imum)?|>=)?\s*(\d+|one|two|three|four|five)\s+verified\s+(?:manager\s+)?references?", ql)
    if m:
        f["min_refs"] = WORDNUM.get(m.group(1), None) or int(m.group(1))
    m = re.search(r"trust\s*(?:score)?\s*(?:>=|above|over|at least)?\s*(\d{2})", ql)
    if m:
        f["min_trust"] = int(m.group(1))
    return f


def llm_parse(q: str) -> dict | None:
    return llm.complete_json(
        "You convert recruiter search queries into filters for an Indian talent registry.",
        f"Query: {q}\nReturn JSON with any of: skills (list, lowercase), city, min_exp, max_exp, ctc_min (LPA), ctc_max (LPA), "
        "pan_verified (bool), aadhaar_verified (bool), degree_verified (bool), degree_kw, min_refs (int), min_trust (int).",
        required=[])


def _verified_refs(db: Session) -> dict[str, int]:
    rows = db.query(Reference.candidate_id).filter(Reference.status == "verified").all()
    out: dict[str, int] = {}
    for (cid,) in rows:
        out[cid] = out.get(cid, 0) + 1
    return out


def _passes(p: CandidateProfile, f: dict, refs: int) -> list[str]:
    """Returns list of failed hard filters (empty == passes)."""
    fails = []
    if f.get("city") and f["city"] != "remote" and (p.city or "").lower() not in (f["city"], {v: k for k, v in CITY_CANON.items()}.get(f["city"], "")):
        fails.append("city")
    if f.get("min_exp") is not None and p.years_experience < f["min_exp"]:
        fails.append("min_exp")
    if f.get("max_exp") is not None and p.years_experience > f["max_exp"]:
        fails.append("max_exp")
    if f.get("ctc_max") is not None and p.current_ctc_lpa is not None and p.current_ctc_lpa > f["ctc_max"]:
        fails.append("ctc_max")
    if f.get("ctc_min") is not None and (p.current_ctc_lpa or 0) < f["ctc_min"]:
        fails.append("ctc_min")
    if f.get("pan_verified") and not p.pan_verified:
        fails.append("pan_verified")
    if f.get("aadhaar_verified") and not p.aadhaar_verified:
        fails.append("aadhaar_verified")
    if f.get("degree_verified") and not p.degree_verified:
        fails.append("degree_verified")
    if f.get("degree_kw"):
        degs = " ".join(e.get("degree", "") for e in p.education or []).lower().replace(".", "")
        if f["degree_kw"] not in degs:
            fails.append("degree_kw")
    if f.get("min_refs") and refs < f["min_refs"]:
        fails.append("min_refs")
    if f.get("min_trust") and p.trust_score < f["min_trust"]:
        fails.append("min_trust")
    return fails


def explain(p: CandidateProfile, user: User, f: dict, sim: float, refs: int) -> dict:
    want = set(f.get("skills") or [])
    have = set(p.skills or []) | set(extract_skills(p.headline or ""))
    overlap = sorted(want & have)
    skill_fit = (len(overlap) / len(want)) if want else 0.6
    tenure = [e for e in p.experience or []]
    verified_jobs = sum(1 for e in tenure if e.get("verified"))
    stability = min(1.0, (p.years_experience / max(len(tenure), 1)) / 2.5) if tenure else 0.5
    ctc_fit = 1.0
    if f.get("ctc_max") and p.expected_ctc_lpa:
        ctc_fit = 1.0 if p.expected_ctc_lpa <= f["ctc_max"] else max(0.0, 1 - (p.expected_ctc_lpa - f["ctc_max"]) / f["ctc_max"])
    authenticity = p.trust_score / 100
    score = 100 * (0.30 * max(sim, 0) + 0.30 * skill_fit + 0.10 * stability + 0.10 * ctc_fit + 0.20 * authenticity)
    reasons = []
    if overlap:
        reasons.append(f"Verified skills match: {', '.join(overlap)}")
    if want - have:
        reasons.append(f"Missing: {', '.join(sorted(want - have))}")
    reasons.append(f"{p.years_experience:g} yrs experience, {verified_jobs}/{len(tenure)} employments verified")
    if p.expected_ctc_lpa:
        reasons.append(f"Expected CTC ₹{p.expected_ctc_lpa:g} LPA" + (" (within band)" if ctc_fit == 1 else " (above band)"))
    badges = [k for k, ok in [("Aadhaar", p.aadhaar_verified), ("PAN", p.pan_verified), ("Degree", p.degree_verified),
                               ("Employment", p.experience_verified), ("CTC", p.ctc_verified)] if ok]
    reasons.append(f"Trust {p.trust_score}/100 — verified: {', '.join(badges) or 'none yet'}; {refs} verified references")
    return {"score": round(score, 1), "components": {"semantic": round(sim, 3), "skills": round(skill_fit, 2),
            "tenure_stability": round(stability, 2), "ctc_fit": round(ctc_fit, 2), "authenticity": round(authenticity, 2)},
            "matched_skills": overlap, "reasons": reasons, "badges": badges}


def search(db: Session, query: str, limit: int = 20, filters: dict | None = None, relax: bool = True) -> dict:
    t0 = time.perf_counter()
    f = filters or parse_query(query)
    used_llm = False
    if filters is None and llm.enabled():
        lf = llm_parse(query)
        if lf:
            used_llm = True
            for k, v in lf.items():
                if v not in (None, "", []) and k not in f:
                    f[k] = v
    t_parse = time.perf_counter()
    refs = _verified_refs(db)
    rows = (db.query(CandidateProfile, User).join(User, User.id == CandidateProfile.user_id)
            .filter(User.role == "candidate", User.is_blocked == False, CandidateProfile.open_to_work == True).all())  # noqa: E712
    passing = {u.id: (p, u) for p, u in rows if not _passes(p, f, refs.get(u.id, 0))}
    near = {}
    if relax and len(passing) < 3:  # show near-misses (only soft filters failed) so recruiters see options
        for p, u in rows:
            fails = _passes(p, f, refs.get(u.id, 0))
            if u.id not in passing and fails and set(fails) <= {"ctc_max", "max_exp", "min_refs", "city"}:
                near[u.id] = (p, u, fails)
    qvec = embed(query)
    ids = list(passing.keys()) + list(near.keys())
    hits = index().search(qvec, ids, k=max(limit * 3, 50))
    sims = dict(hits)
    results = []
    for uid in ids:
        p, u = (passing.get(uid) or near.get(uid))[:2]
        ex = explain(p, u, f, sims.get(uid, 0.0), refs.get(uid, 0))
        if uid in near:
            ex["score"] = round(ex["score"] * 0.8, 1)
            ex["reasons"].insert(0, "Near match — relaxed: " + ", ".join(near[uid][2]))
        results.append({"candidate_id": uid, "name": u.full_name, "headline": p.headline, "city": p.city,
                        "years_experience": p.years_experience, "trust_score": p.trust_score,
                        "skills": p.skills, "current_ctc_lpa": p.current_ctc_lpa if p.ctc_verified else None,
                        "expected_ctc_lpa": p.expected_ctc_lpa, "exact": uid in passing, **ex})
    results.sort(key=lambda r: (-int(r["exact"]), -r["score"]))
    t_end = time.perf_counter()
    return {"query": query, "filters": f, "llm_parsed": used_llm, "vector_backend": index().backend,
            "latency_ms": {"parse": round((t_parse - t0) * 1000, 1), "retrieve_rank": round((t_end - t_parse) * 1000, 1),
                           "total": round((t_end - t0) * 1000, 1)},
            "total_candidates": len(rows), "results": results[:limit]}


def structure_job(prompt: str) -> dict:
    """Prompt-to-JD."""
    if llm.enabled():
        out = llm.complete_json("You are a recruiting operations expert in India. Structure job requisitions.",
                                f"Employer prompt: {prompt}\nReturn JSON: title, description (<=120 words), skills (list), location, "
                                "min_exp, max_exp, ctc_min_lpa, ctc_max_lpa, min_trust (0-100), require_pan (bool), require_degree (bool), min_refs (int)",
                                required=["title", "skills"])
        if out:
            out["_llm"] = True
            return out
    f = parse_query(prompt)
    title_m = re.search(r"(?i)(senior|sr\.?|junior|jr\.?|lead|principal|staff)?\s*([a-z\- ]*(?:engineer|developer|architect|scientist|analyst|designer|manager))", prompt)
    title = " ".join(x for x in (title_m.groups() if title_m else ()) if x).strip().title() or "Software Engineer"
    skills = f.get("skills") or ["python"]
    loc = (f.get("city") or "bengaluru").title()
    return {"title": title,
            "description": (f"We are hiring a {title} in {loc}. You will build and ship production systems using "
                            f"{', '.join(skills[:5])}. Candidates must hold a verified VerifyHire profile."),
            "skills": skills, "location": loc, "min_exp": f.get("min_exp", 0), "max_exp": f.get("max_exp", 30),
            "ctc_min_lpa": f.get("ctc_min"), "ctc_max_lpa": f.get("ctc_max"), "min_trust": f.get("min_trust", 50),
            "require_pan": f.get("pan_verified", True), "require_degree": f.get("degree_verified", False),
            "min_refs": f.get("min_refs", 0), "_llm": False}


def job_filters(job: Job) -> dict:
    return {"skills": job.skills, "city": (job.location or "").lower() or None, "min_exp": job.min_exp,
            "max_exp": job.max_exp, "ctc_max": job.ctc_max_lpa, "pan_verified": job.require_pan or None,
            "degree_verified": job.require_degree or None, "min_refs": job.min_refs or None,
            "min_trust": job.min_trust or None}


def draft_outreach(job: Job, company: Company, name: str, ex: dict) -> str:
    if llm.enabled():
        t = llm.complete("You write concise, warm recruiter outreach. No hype, <=90 words.",
                         f"Candidate {name}; role {job.title} at {company.name}; reasons: {ex['reasons']}")
        if t:
            return t.strip()
    skills = ", ".join(ex["matched_skills"][:3]) or "your background"
    return (f"Hi {name.split()[0]}, I'm with {company.name} (KYB-verified on VerifyHire). Your verified experience in "
            f"{skills} stood out for our {job.title} role in {job.location}. Would you be open to a 20-minute chat this week? "
            f"Your documents stay private unless you approve an access request.")


def match_job(db: Session, job_id: str, top_k: int = 10) -> list[dict]:
    job = db.get(Job, job_id)
    company = db.get(Company, job.company_id)
    with agent_run(db, "talent_matchmaker", f"job:{job_id}") as tr:
        f = job_filters(job)
        f = {k: v for k, v in f.items() if v not in (None, [], "")}
        q = f"{job.title} {' '.join(job.skills or [])} {job.description}"
        res = search(db, q, limit=top_k, filters=f, relax=True)
        tr.step("hybrid_search", **res["latency_ms"], candidates=len(res["results"]))
        existing = {m.candidate_id: m for m in db.query(Match).filter_by(job_id=job_id).all()}
        for r in res["results"]:
            m = existing.get(r["candidate_id"])
            if m:
                m.score, m.breakdown = r["score"], r
            else:
                db.add(Match(job_id=job_id, candidate_id=r["candidate_id"], score=r["score"], breakdown=r,
                             outreach_draft=draft_outreach(job, company, r["name"], r)))
                if r["exact"]:
                    notify(db, r["candidate_id"], f"New verified job match: {job.title}",
                           f"{company.name} · {job.location} · match {r['score']:.0f}%", "job")
        db.commit()
        tr.decision = f"top_{len(res['results'])}"
        tr.summary = f"{len(res['results'])} matches for '{job.title}' in {res['latency_ms']['total']} ms"
        tr.output = {"job_id": job_id, "matches": [r["candidate_id"] for r in res["results"]]}
    return res["results"]


def rematch_all(db: Session):
    for j in db.query(Job).filter_by(status="open").all():
        match_job(db, j.id)
