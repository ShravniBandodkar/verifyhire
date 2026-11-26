"""Agent 2 — Corporate KYB Underwriting Agent (replaces B2B onboarding specialists).

LangGraph: formats → registries → consistency → risk_signals → narrative → decide
"""
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from ..models import Company, User
from ..services import llm
from ..services.gov import (PAN_ENTITY, get_gov_adapter, gstin_valid, name_similarity, pan_valid, parse_cin)
from .base import agent_run, notify

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com", "proton.me", "icloud.com"}
REVENUE_MIN_HEADCOUNT = {"< 1 Cr": 1, "1-10 Cr": 5, "10-100 Cr": 30, "100-500 Cr": 150, "500+ Cr": 500}


class KybState(TypedDict, total=False):
    ctx: Any
    co: Any
    checks: list
    risk: int
    regs: dict


def _add(s, name, ok, detail, weight):
    s["checks"].append({"check": name, "ok": ok, "detail": detail, "weight": weight})
    if not ok:
        s["risk"] += weight


def n_formats(s: KybState):
    co = s["co"]
    s["checks"], s["risk"] = [], 0
    _add(s, "Corporate PAN format", pan_valid(co.pan), co.pan or "missing", 30)
    if pan_valid(co.pan):
        ent = PAN_ENTITY.get(co.pan[3], "?")
        _add(s, "PAN entity type is a business", co.pan[3] in "CFT", f"4th char '{co.pan[3]}' = {ent}", 25)
    _add(s, "GSTIN format & checksum", gstin_valid(co.gstin), co.gstin or "missing", 20)
    _add(s, "CIN/LLPIN structure", parse_cin(co.cin) is not None, co.cin or "missing", 20)
    s["ctx"]["trace"].step("formats", risk=s["risk"])
    return s


def n_registries(s: KybState):
    gov, co = get_gov_adapter(), s["co"]
    s["regs"] = {
        "mca": gov.mca_lookup(co.cin) if co.cin else {},
        "gst": gov.gstin_lookup(co.gstin) if co.gstin else {},
        "pan": gov.pan_verify(co.pan, co.name) if co.pan else {},
        "epfo": gov.epfo_headcount(co.name),
        "domain_age": gov.domain_age_years(co.domain) if co.domain else None,
    }
    s["ctx"]["trace"].step("registry_lookups", sources=["MCA21", "GSTN", "NSDL", "EPFO", "WHOIS"])
    return s


def n_consistency(s: KybState):
    co, r = s["co"], s["regs"]
    if r.get("gst", {}).get("ok"):
        _add(s, "GSTIN embeds the same PAN", r["gst"]["embedded_pan"] == co.pan.upper(),
             f"GSTIN PAN {r['gst']['embedded_pan']} vs {co.pan}", 30)
    mca = r.get("mca", {})
    if mca.get("ok"):
        _add(s, "Company found in MCA21", mca.get("found", False), "registry hit" if mca.get("found") else "no record", 20)
        if mca.get("record"):
            sim = name_similarity(mca["record"]["name"], co.name)
            _add(s, "Registered name matches", sim >= 0.8, f"similarity {sim}", 20)
            _add(s, "MCA status Active", mca["record"]["status"] == "Active", mca["record"]["status"], 25)
        if co.incorporation_year:
            _add(s, "CIN year matches incorporation year", mca["parsed"]["year"] == co.incorporation_year,
                 f"CIN {mca['parsed']['year']} vs declared {co.incorporation_year}", 15)
    pan = r.get("pan", {})
    if pan.get("name_match") is not None:
        _add(s, "NSDL PAN name matches", pan["name_match"] >= 0.8, f"similarity {pan['name_match']}", 20)
    s["ctx"]["trace"].step("consistency", risk=s["risk"])
    return s


def n_signals(s: KybState):
    co, r = s["co"], s["regs"]
    db: Session = s["ctx"]["db"]
    admin = db.query(User).filter_by(company_id=co.id, role="employer_admin").first()
    if admin:
        dom = admin.email.split("@")[-1].lower()
        _add(s, "Admin uses corporate email", dom not in FREE_MAIL, admin.email, 20)
        if co.domain:
            _add(s, "Admin email matches company domain", dom == co.domain.lower(), f"{dom} vs {co.domain}", 15)
    age = r.get("domain_age")
    if age is not None:
        _add(s, "Domain age ≥ 1 year", age >= 1, f"{age} years", 15)
    ep = r.get("epfo", {}).get("headcount")
    if ep is not None and co.headcount:
        ratio = ep / max(co.headcount, 1)
        _add(s, "EPFO headcount corroborates declared headcount", ratio >= 0.5,
             f"EPFO {ep} vs declared {co.headcount}", 25)
    need = REVENUE_MIN_HEADCOUNT.get(co.revenue_bracket)
    if need and co.headcount:
        _add(s, "Revenue bracket plausible for headcount", co.headcount >= need * 0.3,
             f"{co.revenue_bracket} with {co.headcount} staff", 10)
    rec = (r.get("mca") or {}).get("record")
    if rec:
        stale = int(rec["last_filing"][:4]) < date.today().year - 2
        _add(s, "Recent MCA annual filing", not stale, f"last filing {rec['last_filing']}", 15)
        _add(s, "Paid-up capital above shell threshold", rec["paid_up_capital_cr"] >= 0.5,
             f"₹{rec['paid_up_capital_cr']} Cr", 10)
    s["ctx"]["trace"].step("risk_signals", risk=s["risk"])
    return s


def n_decide(s: KybState):
    db: Session = s["ctx"]["db"]
    co, tr = s["co"], s["ctx"]["trace"]
    risk = min(s["risk"], 100)
    status = "approved" if risk < 30 else ("flagged" if risk < 60 else "rejected")
    failed = [c for c in s["checks"] if not c["ok"]]
    narrative = None
    if llm.enabled():
        out = llm.complete_json("You are a KYB underwriter at an Indian hiring platform.",
                                f"Company: {co.name}. Checks: {s['checks']}. Decision {status}, risk {risk}. "
                                "Write JSON {\"narrative\": str (<=60 words, plain, factual)}", required=["narrative"])
        if out:
            tr.llm_used, narrative = True, out["narrative"]
    if not narrative:
        narrative = (f"{co.name}: {len(s['checks']) - len(failed)}/{len(s['checks'])} checks passed. "
                     + ("Failed: " + "; ".join(c["check"] for c in failed[:4]) + "." if failed else "All registry, consistency and risk checks passed."))
    co.kyb_status, co.risk_score = status, risk
    co.kyb_report = {"checks": s["checks"], "narrative": narrative, "registries": {k: v for k, v in s["regs"].items() if k != "pan"}}
    for u in db.query(User).filter_by(company_id=co.id).all():
        notify(db, u.id, f"KYB {status}", narrative, "success" if status == "approved" else "warning")
    db.commit()
    tr.decision, tr.summary, tr.needs_human = status, narrative, status == "flagged"
    tr.output = {"company_id": co.id, "risk": risk, "failed": [c["check"] for c in failed]}
    return s


def _build():
    g = StateGraph(KybState)
    chain = [("formats", n_formats), ("registries", n_registries), ("consistency", n_consistency),
             ("signals", n_signals), ("decide", n_decide)]
    for n, f in chain:
        g.add_node(n, f)
    g.set_entry_point("formats")
    for (a, _), (b, _) in zip(chain, chain[1:]):
        g.add_edge(a, b)
    g.add_edge("decide", END)
    return g.compile()


GRAPH = _build()


def run(db: Session, company_id: str) -> dict:
    co = db.get(Company, company_id)
    with agent_run(db, "kyb_underwriting", f"company:{company_id}") as tr:
        GRAPH.invoke({"ctx": {"db": db, "trace": tr}, "co": co})
    return {"status": co.kyb_status, "risk": co.risk_score, "report": co.kyb_report}
