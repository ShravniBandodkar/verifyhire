"""Agent 1 — KYC & Document Forensics Agent (replaces KYC/BGV verification analysts).

LangGraph pipeline:  decrypt → extract → classify → parse_fields → [llm_vision_review] →
forensics → gov_verify → decide → apply
"""
import io
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from ..core import vault
from ..models import CandidateProfile, Document, User
from ..services import docs as D
from ..services import llm
from ..services.gov import aadhaar_valid, get_gov_adapter, name_similarity, pan_valid
from .base import agent_run, notify, sign_badge

EDIT_TOOLS = ["photoshop", "gimp", "canva", "ilovepdf", "sejda", "pdfescape", "smallpdf", "pixlr",
              "foxit phantompdf", "nitro", "pdf-xchange", "inkscape", "affinity"]


class KycState(TypedDict, total=False):
    ctx: Any
    doc: Any
    data: bytes
    text: str
    meta: dict
    doc_type: str
    fields: dict
    forensics: dict
    gov: dict
    risk: int
    verdict: str
    reasons: list


# ---------------- nodes ----------------
def n_decrypt(s: KycState) -> KycState:
    d = s["doc"]
    s["data"] = vault.get(d.storage_key, d.wrapped_dek, d.kek_version, d.owner_id)
    s["ctx"]["trace"].step("decrypt", bytes=len(s["data"]))
    return s


def n_extract(s: KycState) -> KycState:
    d = s["doc"]
    text, meta = D.extract_text(d.filename, d.mime, s["data"])
    s["text"], s["meta"] = text, meta
    s["ctx"]["trace"].step("extract_text", chars=len(text), ocr=d.mime.startswith("image/"))
    return s


def classify_text(filename: str, text: str, mime: str) -> str:
    t, f = text.lower(), filename.lower()
    if "aadhaar" in f or "aadhar" in f or "unique identification" in t or "aadhaar" in t or "आधार" in text:
        return "aadhaar"
    if "pan" in re.split(r"[^a-z]", f) or "permanent account number" in t or "income tax department" in t:
        return "pan"
    if any(k in t for k in ["payslip", "salary slip", "pay slip", "form 16", "form no. 16", "earnings"]) or "payslip" in f:
        return "payslip"
    if any(k in t for k in ["relieving letter", "experience letter", "to whom it may concern", "relieved from"]) or "relieving" in f or "experience_letter" in f:
        return "experience_letter"
    if any(k in t for k in ["degree of", "is hereby conferred", "has been awarded", "convocation", "marksheet",
                            "grade card", "transcript"]) or "degree" in f or "marksheet" in f:
        return "degree"
    if sum(k in t for k in ["experience", "skills", "education", "projects", "summary"]) >= 2 or "resume" in f or "cv" in re.split(r"[^a-z]", f):
        return "resume"
    if mime.startswith("image/") and len(text.strip()) < 15:
        return "photo"
    return "other"


def n_classify(s: KycState) -> KycState:
    d = s["doc"]
    hinted = d.doc_type if d.doc_type not in ("", "auto", "other") else None
    detected = classify_text(d.filename, s["text"], d.mime)
    s["doc_type"] = hinted or detected
    s["ctx"]["trace"].step("classify", detected=detected, hinted=hinted, final=s["doc_type"])
    return s


def _date_norm(v: str) -> str:
    m = re.match(r"(\d{2})[/-](\d{2})[/-](\d{4})", v or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else (v or "")


def parse_fields(doc_type: str, text: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    f: dict = {}
    dob = D.DOB_RE.search(text)
    if dob:
        f["dob"] = _date_norm(dob.group(1))
    if doc_type == "aadhaar":
        m = D.AADHAAR_RE.search(text)
        if m:
            f["aadhaar_number"] = re.sub(r"\s", "", m.group(1))
        for i, l in enumerate(lines):
            if D.DOB_RE.search(l) and i > 0:
                f["name"] = re.sub(r"(?i)^name[:\s]*", "", lines[i - 1]); break
        g = re.search(r"\b(MALE|FEMALE|Male|Female)\b", text)
        if g:
            f["gender"] = g.group(1).title()
    elif doc_type == "pan":
        m = D.PAN_TXT_RE.search(text.upper())
        if m:
            f["pan_number"] = m.group(1)
        for i, l in enumerate(lines):
            ll = l.lower()
            if re.match(r"^(name|नाम)", ll) and "father" not in ll and i + 1 < len(lines):
                f.setdefault("name", re.sub(r"(?i)^name[:/\s]*", "", l) or lines[i + 1])
                if len(f["name"]) < 3:
                    f["name"] = lines[i + 1]
            if "father" in ll:
                val = re.sub(r"(?i)^.*father'?s?\s*name[:/\s]*", "", l)
                f["father_name"] = val if len(val) > 2 else (lines[i + 1] if i + 1 < len(lines) else "")
    elif doc_type == "degree":
        m = re.search(r"(?i)(Bachelor|Master|Doctor)\s+of\s+([A-Za-z ]+?)(?:\s+in\s+([A-Za-z ]+))?(?:\n|\.|,| with| on)", text)
        if m:
            lvl = {"bachelor": "B", "master": "M", "doctor": "Ph.D"}[m.group(1).lower()]
            sub = m.group(2).strip().lower()
            short = {"technology": f"{lvl}.Tech", "engineering": f"{lvl}.E", "science": f"{lvl}S" if lvl == "M" else "B.Sc",
                     "computer applications": f"{lvl}CA", "business administration": f"{lvl}BA"}.get(sub, f"{m.group(1)} of {m.group(2).strip()}")
            f["degree"] = f"{short} {m.group(3).strip()}".strip() if m.group(3) else short
        inst = re.search(r"(?i)([A-Z][A-Za-z.& ]+(University|Institute of Technology|Institute|College|IIT [A-Za-z]+|BITS [A-Za-z]+))", text)
        if inst:
            f["institution"] = inst.group(1).strip()
        y = re.findall(r"\b(19[89]\d|20[0-3]\d)\b", text)
        if y:
            f["year"] = max(y)
        nm = re.search(r"(?i)(?:certify that|conferred upon|awarded to)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})", text)
        if nm:
            f["name"] = nm.group(1).strip()
    elif doc_type == "experience_letter":
        nm = re.search(r"(?i)(?:that|mr\.?|ms\.?|mrs\.?)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})\s+(?:was|has been|worked)", text)
        if nm:
            f["name"] = nm.group(1)
        dates = re.findall(r"(\d{1,2}[ /-](?:[A-Za-z]{3,9}|\d{1,2})[ /,-]*\d{4}|[A-Za-z]{3,9}\s+\d{4})", text)
        if len(dates) >= 2:
            f["start"], f["end"] = dates[0], dates[1]
        t = re.search(r"(?i)as\s+(?:an?\s+)?([A-Z][A-Za-z ]{3,40}?)(?:\s+from|\s+in|\.|,)", text)
        if t:
            f["title"] = t.group(1).strip()
        c = re.search(r"(?i)([A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+)*\s+(?:Private Limited|Pvt\.? Ltd\.?|Limited|Ltd\.?|LLP|Inc\.?))", text)
        if c:
            f["company"] = c.group(1)
    elif doc_type == "payslip":
        lpa = re.search(r"(?i)(?:annual\s+)?ctc[^0-9\n]{0,20}([\d.]+)\s*(?:lpa|lakhs?|l\b)", text)
        annual = re.search(r"(?i)(?:annual\s+ctc|ctc\s+per\s+annum|annual\s+compensation)[^0-9\n]{0,20}([\d,]{6,})", text)
        gross = re.search(r"(?i)(?:gross\s+(?:salary|pay|earnings)|total\s+earnings)[^0-9\n]{0,20}([\d,]{4,})", text)
        if lpa:
            f["ctc_lpa"] = round(float(lpa.group(1)), 2)
        elif annual:
            f["ctc_lpa"] = round(float(annual.group(1).replace(",", "")) / 100000, 2)
        elif gross:
            f["ctc_lpa"] = round(float(gross.group(1).replace(",", "")) * 12 / 100000, 2)
            f["ctc_basis"] = "monthly gross x 12"
        c = re.search(r"(?i)([A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+)*\s+(?:Private Limited|Pvt\.? Ltd\.?|Limited|Ltd\.?))", text)
        if c:
            f["company"] = c.group(1)
    elif doc_type == "resume":
        from ..services.embeddings import extract_skills
        f["skills"] = extract_skills(text)
        em = D.EMAIL_RE.search(text)
        if em:
            f["email"] = em.group(0)
        ph = D.PHONE_RE.search(text)
        if ph:
            f["phone"] = ph.group(0)
        yrs = re.search(r"(\d{1,2}(?:\.\d)?)\+?\s*(?:years|yrs)", text, re.I)
        if yrs:
            f["years_experience"] = float(yrs.group(1))
        if lines:
            f["name"] = lines[0][:80]
    return f


def n_parse(s: KycState) -> KycState:
    s["fields"] = parse_fields(s["doc_type"], s["text"])
    s["ctx"]["trace"].step("parse_fields", fields=sorted(s["fields"].keys()))
    return s


def n_llm_review(s: KycState) -> KycState:
    """Vision-language model pass: layout-aware extraction + tamper opinion (optional)."""
    tr = s["ctx"]["trace"]
    if not llm.enabled():
        tr.step("vlm_review", skipped="no LLM configured")
        return s
    d = s["doc"]
    image = (s["data"], d.mime) if d.mime in ("image/jpeg", "image/png") else None
    out = llm.complete_json(
        "You are a document forensics analyst for Indian KYC. Extract fields and assess tampering.",
        f"Document type guess: {s['doc_type']}. OCR/text:\n{s['text'][:6000]}\n\n"
        "Return JSON: {\"doc_type\": str, \"fields\": {..}, \"tamper_signals\": [str], \"tamper_risk\": 0-100}. "
        "Fields may include name, dob (YYYY-MM-DD), father_name, pan_number, aadhaar_number, degree, institution, year, "
        "company, title, start, end, ctc_lpa, skills (list), years_experience.",
        image=image, required=["fields"])
    if out:
        tr.llm_used = True
        for k, v in (out.get("fields") or {}).items():
            if v and k not in s["fields"]:
                s["fields"][k] = v
        s.setdefault("forensics", {})["llm"] = {"signals": out.get("tamper_signals", []),
                                                "risk": out.get("tamper_risk")}
        tr.step("vlm_review", ok=True)
    else:
        tr.step("vlm_review", ok=False)
    return s


def n_forensics(s: KycState) -> KycState:
    ctx, d, meta = s["ctx"], s["doc"], s["meta"]
    db: Session = ctx["db"]
    fx = s.setdefault("forensics", {})
    signals, risk = [], 0

    # 1. Editing software fingerprints
    tool = " ".join([meta.get("producer", ""), meta.get("creator", ""), meta.get("software", "")]).lower()
    hit = next((t for t in EDIT_TOOLS if t in tool), None)
    if hit:
        ident = s["doc_type"] in ("pan", "aadhaar")
        signals.append(f"Edited with '{hit}' (metadata)" + (" — identity cards should be camera/scan originals" if ident else ""))
        risk += 40 if ident else 30
    if meta.get("modified") and meta.get("created") and meta["modified"][:10] != meta["created"][:10]:
        signals.append("PDF modified after creation"); risk += 10
    # 2. Font anomaly — certificates normally use 1-3 font families
    if s["doc_type"] in ("pan", "aadhaar", "degree", "experience_letter", "payslip") and len(meta.get("fonts", [])) > 5:
        signals.append(f"{len(meta['fonts'])} distinct fonts embedded (font anomaly)"); risk += 20
    # 3. Error Level Analysis for JPEGs (pixel splicing)
    if d.mime == "image/jpeg":
        ela = D.error_level_analysis(s["data"])
        fx["ela"] = ela
        if ela.get("suspicious"):
            signals.append(f"Uneven JPEG error levels (ELA ratio {ela['ela_ratio']}) — possible splice"); risk += 30
    # 4. Identity number integrity
    f = s["fields"]
    if s["doc_type"] == "aadhaar" and f.get("aadhaar_number") and not aadhaar_valid(f["aadhaar_number"]):
        signals.append("Aadhaar number fails Verhoeff checksum"); risk += 50
    if s["doc_type"] == "pan" and f.get("pan_number") and not pan_valid(f["pan_number"]):
        signals.append("PAN structure invalid"); risk += 50
    # 5. Duplicate document across accounts (synthetic identity / reuse)
    dup = db.query(Document).filter(Document.sha256 == d.sha256, Document.owner_id != d.owner_id).first()
    if dup:
        signals.append("Identical file already uploaded by another account"); risk += 60
    # 6. Name cross-match with the account holder
    owner = db.get(User, d.owner_id)
    if f.get("name") and owner and s["doc_type"] in ("aadhaar", "pan", "degree", "experience_letter"):
        sim = name_similarity(f["name"], owner.full_name)
        fx["name_match"] = sim
        if sim < 0.6:
            signals.append(f"Name on document ('{f['name']}') does not match account holder (similarity {sim})"); risk += 25
    # 7. LLM opinion (bounded weight — deterministic checks dominate)
    llm_r = (fx.get("llm") or {}).get("risk")
    if isinstance(llm_r, (int, float)):
        risk += int(min(llm_r, 100) * 0.25)
        signals += [f"VLM: {x}" for x in (fx["llm"].get("signals") or [])[:3]]
    fx["signals"], fx["risk"] = signals, min(risk, 100)
    s["risk"] = fx["risk"]
    ctx["trace"].step("forensics", risk=fx["risk"], signals=len(signals))
    return s


def n_gov(s: KycState) -> KycState:
    gov = get_gov_adapter()
    f, t = s["fields"], s["doc_type"]
    owner = s["ctx"]["db"].get(User, s["doc"].owner_id)
    res: dict = {"adapter": gov.name}
    if t == "pan" and f.get("pan_number"):
        res["pan"] = gov.pan_verify(f["pan_number"], f.get("name") or owner.full_name, f.get("dob", ""))
    elif t == "degree" and f.get("institution") and f.get("degree"):
        res["nad"] = gov.nad_verify(f["institution"], f["degree"], f.get("year", ""), owner.full_name)
    elif t == "aadhaar":
        res["note"] = "Aadhaar confirmed via OTP e-KYC flow; card image cross-checked against e-KYC token"
    s["gov"] = res
    s["ctx"]["trace"].step("gov_verify", checks=list(res.keys()))
    return s


def n_decide(s: KycState) -> KycState:
    risk, gov, t = s.get("risk", 0), s.get("gov", {}), s["doc_type"]
    db: Session = s["ctx"]["db"]
    reasons = list(s["forensics"].get("signals", []))
    confirmed = False
    if t == "pan" and gov.get("pan", {}).get("status") == "NOT_FOUND":
        reasons.append("PAN not found in NSDL registry")
        risk += 30
    if t == "pan" and gov.get("pan", {}).get("status") == "VALID":
        nm = gov["pan"].get("name_match")
        confirmed = nm is None or nm >= 0.75
        if nm is not None and nm < 0.75:
            reasons.append("NSDL registered name mismatch"); risk += 30
    elif t == "degree":
        confirmed = bool(gov.get("nad", {}).get("found"))
        if not confirmed:
            reasons.append("Degree not found in NAD/DigiLocker — needs issuer confirmation")
    elif t == "aadhaar":
        prof = db.get(CandidateProfile, s["doc"].owner_id)
        num = s["fields"].get("aadhaar_number")
        if prof and prof.aadhaar_token and num:
            confirmed = vault.tokenize(num, "aadhaar") == prof.aadhaar_token
            if not confirmed:
                reasons.append("Card number differs from e-KYC verified Aadhaar"); risk += 40
        else:
            reasons.append("Complete Aadhaar OTP e-KYC to confirm this card")
    elif t == "experience_letter":
        confirmed = bool(s["fields"].get("company"))
    elif t == "payslip":
        confirmed = bool(s["fields"].get("ctc_lpa"))
    elif t in ("resume", "photo", "other"):
        confirmed = True
    if risk >= 70:
        verdict = "rejected"
    elif risk >= 35 or not confirmed:
        verdict = "flagged"
    else:
        verdict = "verified"
    s["risk"], s["verdict"], s["reasons"] = min(risk, 100), verdict, reasons
    s["ctx"]["trace"].step("decide", verdict=verdict, risk=s["risk"])
    return s


def _redact_aadhaar_image(data: bytes) -> bytes | None:
    """UIDAI masking: black out the first 8 digits of the Aadhaar number on the stored image."""
    try:
        import pytesseract
        from PIL import Image, ImageDraw
        img = Image.open(io.BytesIO(data)).convert("RGB")
        dd = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        groups = [i for i, w in enumerate(dd["text"]) if re.fullmatch(r"\d{4}", w.strip() or "x")]
        draw = ImageDraw.Draw(img)
        redacted = 0
        for a, b, c in zip(groups, groups[1:], groups[2:]):
            if b == a + 1 and c == b + 1:
                for i in (a, b):
                    draw.rectangle([dd["left"][i], dd["top"][i], dd["left"][i] + dd["width"][i],
                                    dd["top"][i] + dd["height"][i]], fill="black")
                redacted += 1
        if not redacted:
            return None
        out = io.BytesIO(); img.save(out, "PNG")
        return out.getvalue()
    except Exception:
        return None


def n_apply(s: KycState) -> KycState:
    db: Session = s["ctx"]["db"]
    d: Document = s["doc"]
    f = dict(s["fields"])
    prof = db.get(CandidateProfile, d.owner_id)
    # Never persist raw identity numbers in extracted data
    if "aadhaar_number" in f:
        f["aadhaar_masked"] = vault.mask_aadhaar(f.pop("aadhaar_number"))
        red = _redact_aadhaar_image(s["data"]) if d.mime.startswith("image/") else None
        if red:
            blob = vault.put(red, d.owner_id)
            d.storage_key, d.wrapped_dek, d.kek_version, d.mime = blob.key, blob.wrapped_dek, blob.kek_version, "image/png"
            s["ctx"]["trace"].step("uidai_masking", redacted=True)
    if "pan_number" in f:
        pan = f.pop("pan_number")
        f["pan_masked"] = vault.mask_pan(pan)
        if prof and s["verdict"] == "verified":
            prof.pan_masked, prof.pan_hash, prof.pan_verified = vault.mask_pan(pan), vault.tokenize(pan, "pan"), True
            prof.pan_sealed = vault.seal_field(pan.upper(), d.owner_id)
            if s["gov"].get("pan", {}).get("father_name") and not prof.father_name:
                prof.father_name = s["gov"]["pan"]["father_name"]
    d.doc_type, d.extracted, d.status = s["doc_type"], f, s["verdict"]
    d.forensics = {**s["forensics"], "risk": s["risk"], "gov": s.get("gov", {}), "reasons": s["reasons"]}
    if s["verdict"] == "verified":
        d.badge = sign_badge({"doc_id": d.id, "sha256": d.sha256, "type": s["doc_type"], "verdict": "verified",
                              "agent": "kyc_forensics", "risk": s["risk"]})
    if prof and s["verdict"] == "verified":
        if s["doc_type"] == "degree":
            prof.degree_verified = True
            edu = [e for e in (prof.education or []) if e.get("degree", "").lower() != str(f.get("degree", "")).lower()]
            edu.append({"degree": f.get("degree", ""), "institution": f.get("institution", ""), "year": f.get("year", ""), "verified": True})
            prof.education = edu
        if s["doc_type"] == "experience_letter":
            prof.experience_verified = True
            exp = list(prof.experience or [])
            for e in exp:
                if f.get("company") and name_similarity(e.get("company", ""), f["company"]) > 0.7:
                    e["verified"] = True
            if not any(e.get("verified") for e in exp) and f.get("company"):
                exp.append({"company": f["company"], "title": f.get("title", ""), "start": f.get("start", ""),
                            "end": f.get("end", ""), "verified": True})
            prof.experience = exp
        if s["doc_type"] == "payslip" and f.get("ctc_lpa"):
            prof.ctc_verified = True
            prof.current_ctc_lpa = float(f["ctc_lpa"])
        if s["doc_type"] == "aadhaar":
            prof.photo_verified = prof.photo_verified or False
    db.commit()
    tr = s["ctx"]["trace"]
    tr.decision = s["verdict"]
    tr.needs_human = s["verdict"] == "flagged" and s["risk"] >= 35
    tr.summary = f"{s['doc_type']} → {s['verdict']} (risk {s['risk']}). " + "; ".join(s["reasons"][:3])
    tr.output = {"doc_id": d.id, "doc_type": s["doc_type"], "risk": s["risk"], "fields": sorted(f.keys())}
    label = {"verified": "verified ✓", "flagged": "needs attention", "rejected": "rejected"}[s["verdict"]]
    notify(db, d.owner_id, f"{s['doc_type'].replace('_', ' ').title()} {label}",
           "; ".join(s["reasons"][:2]) or "Verification badge issued.", "success" if s["verdict"] == "verified" else "warning")
    db.commit()
    return s


def _build():
    g = StateGraph(KycState)
    for name, fn in [("decrypt", n_decrypt), ("extract", n_extract), ("classify", n_classify), ("parse", n_parse),
                     ("vlm_review", n_llm_review), ("forensics", n_forensics), ("gov_verify", n_gov),
                     ("decide", n_decide), ("apply", n_apply)]:
        g.add_node(name, fn)
    g.set_entry_point("decrypt")
    chain = ["decrypt", "extract", "classify", "parse", "vlm_review", "forensics", "gov_verify", "decide", "apply"]
    for a, b in zip(chain, chain[1:]):
        g.add_edge(a, b)
    g.add_edge("apply", END)
    return g.compile()


GRAPH = _build()


def run(db: Session, doc_id: str) -> dict:
    doc = db.get(Document, doc_id)
    if not doc:
        return {"error": "not found"}
    doc.status = "processing"; db.commit()
    with agent_run(db, "kyc_forensics", f"document:{doc_id}", doc.owner_id) as tr:
        try:
            out = GRAPH.invoke({"ctx": {"db": db, "trace": tr}, "doc": doc})
            return {"doc_type": out["doc_type"], "verdict": out["verdict"], "risk": out["risk"], "reasons": out["reasons"]}
        except Exception as e:
            db.rollback()
            doc.status = "flagged"; doc.forensics = {"error": str(e)}; db.commit()
            tr.decision, tr.summary, tr.needs_human = "error", f"Pipeline error: {e}", True
            return {"error": str(e)}


# ---------------- Liveness (selfie frames) ----------------
def liveness_check(frames: list[bytes]) -> dict:
    """Active liveness (sandbox-grade): requires a detected face in each frame and natural
    inter-frame motion (a printed photo / static replay shows ~zero motion)."""
    try:
        import cv2
        import numpy as np
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces, grays = [], []
        for fb in frames:
            arr = cv2.imdecode(np.frombuffer(fb, np.uint8), cv2.IMREAD_GRAYSCALE)
            if arr is None:
                continue
            arr = cv2.resize(arr, (320, int(320 * arr.shape[0] / arr.shape[1])))
            grays.append(arr)
            faces.append(len(cascade.detectMultiScale(arr, 1.1, 5, minSize=(40, 40))) > 0)
        if len(grays) < 2:
            return {"live": False, "reason": "Need at least 2 frames"}
        motion = float(np.mean([np.mean(cv2.absdiff(a, b)) for a, b in zip(grays, grays[1:])]))
        face_ratio = sum(faces) / len(faces)
        live = face_ratio >= 0.5 and 0.8 < motion < 60
        return {"live": live, "face_ratio": round(face_ratio, 2), "motion": round(motion, 2),
                "reason": "ok" if live else ("No face detected" if face_ratio < 0.5 else "Insufficient natural motion")}
    except Exception as e:
        return {"live": False, "reason": f"liveness engine error: {e}"}
