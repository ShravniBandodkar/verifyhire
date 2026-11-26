"""Pluggable government-integration adapter layer.

`SandboxGovAdapter` mimics DigiLocker/UIDAI OTP e-KYC, NSDL PAN, MCA21, GSTN and NAD with
realistic validation (Verhoeff checksum for Aadhaar, PAN structure, GSTIN mod-36 checksum,
CIN structure). A production adapter (e.g. `DigiLockerAdapter`) implements the same interface
with licensed credentials — nothing else in the system changes.
"""
import re
from abc import ABC, abstractmethod
from difflib import SequenceMatcher

from ..core.config import settings

# ---------- Format / checksum validators (real algorithms) ----------
_V_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],
        [4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],
        [8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
_V_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
        [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_V_INV = [0,4,3,2,1,5,6,7,8,9]


def verhoeff_valid(num: str) -> bool:
    c = 0
    for i, d in enumerate(reversed(num)):
        c = _V_D[c][_V_P[i % 8][int(d)]]
    return c == 0


def verhoeff_digit(num: str) -> str:
    c = 0
    for i, d in enumerate(reversed(num)):
        c = _V_D[c][_V_P[(i + 1) % 8][int(d)]]
    return str(_V_INV[c])


def aadhaar_valid(num: str) -> bool:
    d = re.sub(r"\D", "", num)
    return len(d) == 12 and d[0] not in "01" and verhoeff_valid(d)


PAN_RE = re.compile(r"^[A-Z]{3}[ABCFGHLJPT][A-Z][0-9]{4}[A-Z]$")
PAN_ENTITY = {"P": "Individual", "C": "Company", "F": "Firm/LLP", "H": "HUF", "A": "AOP",
              "T": "Trust", "B": "BOI", "L": "Local Authority", "J": "Artificial Juridical", "G": "Government"}


def pan_valid(pan: str) -> bool:
    return bool(PAN_RE.match(pan.upper()))


_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = _GST_CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def gstin_valid(g: str) -> bool:
    g = g.upper()
    return bool(re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", g)) and gstin_checksum(g[:14]) == g[14]


CIN_RE = re.compile(r"^([LU])([0-9]{5})([A-Z]{2})([0-9]{4})([A-Z]{3})([0-9]{6})$")


def parse_cin(cin: str) -> dict | None:
    m = CIN_RE.match(cin.upper())
    if not m:
        return None
    return {"listed": m.group(1) == "L", "industry": m.group(2), "state": m.group(3),
            "year": int(m.group(4)), "ownership": m.group(5), "reg_no": m.group(6)}


def name_similarity(a: str, b: str) -> float:
    norm = lambda s: " ".join(sorted(re.sub(r"[^a-z ]", "", s.lower()).split()))
    return round(SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


# ---------- Adapter interface ----------
class GovAdapter(ABC):
    name = "abstract"

    @abstractmethod
    def aadhaar_send_otp(self, aadhaar: str) -> dict: ...
    @abstractmethod
    def aadhaar_verify_otp(self, aadhaar: str, otp: str) -> dict: ...
    @abstractmethod
    def pan_verify(self, pan: str, name: str, dob: str = "") -> dict: ...
    @abstractmethod
    def mca_lookup(self, cin: str) -> dict: ...
    @abstractmethod
    def gstin_lookup(self, gstin: str) -> dict: ...
    @abstractmethod
    def nad_verify(self, institution: str, degree: str, year: str, name: str) -> dict: ...
    @abstractmethod
    def epfo_headcount(self, company_name: str) -> dict: ...


# Synthetic registry records used by the sandbox (no real persons/companies).
SANDBOX_PAN = {
    "ABCPK1234K": {"name": "Aisha Kapoor", "dob": "1997-03-14", "father": "Vikram Kapoor"},
    "BQRPK4821M": {"name": "Rahul Kumar", "dob": "1994-07-02", "father": "Suresh Kumar"},
    "CTLPA7715Q": {"name": "Ananya Iyer", "dob": "1996-11-21", "father": "Venkat Iyer"},
    "DFHPM3309B": {"name": "Arjun Mehta", "dob": "1992-01-30", "father": "Rakesh Mehta"},
    "EKZPR5520L": {"name": "Priya Reddy", "dob": "1995-05-09", "father": "Mohan Reddy"},
    "BKRPM2045L": {"name": "Rohan Mehta", "dob": "1995-08-22", "father": "Suresh Mehta"},
    "CDEPN7781R": {"name": "Priya Nair", "dob": "1996-11-05", "father": "Mohan Nair"},
    "AAACN4455F": {"name": "Nimbus Cloudworks Private Limited", "dob": "2014-06-12", "father": ""},
    "AAFCQ9921H": {"name": "Quanta Retail Analytics Private Limited", "dob": "2019-02-01", "father": ""},
}
SANDBOX_MCA = {
    "U72200KA2014PTC074512": {"name": "Nimbus Cloudworks Private Limited", "status": "Active",
                               "incorporated": "2014-06-12", "paid_up_capital_cr": 12.5,
                               "directors": ["Kavita Rao", "Imran Sheikh"], "last_filing": "2025-10-30"},
    "U74999MH2019PTC321908": {"name": "Quanta Retail Analytics Private Limited", "status": "Active",
                               "incorporated": "2019-02-01", "paid_up_capital_cr": 0.1,
                               "directors": ["Dev Malhotra"], "last_filing": "2022-03-31"},
}
SANDBOX_EPFO = {"nimbus cloudworks private limited": 1180, "quanta retail analytics private limited": 3}
SANDBOX_DOMAIN_AGE_YEARS = {"nimbuscloud.example": 11, "quanta-retail.example": 0.2}
SANDBOX_NAD = {
    ("anna university", "b.e computer science"): ["aisha kapoor", "rohan mehta", "priya nair"],
    ("bits pilani", "m.tech software systems"): ["aisha kapoor"],
    ("iit bombay", "b.tech computer science"): ["arjun mehta", "rahul kumar"],
    ("vit vellore", "b.tech information technology"): ["ananya iyer", "priya reddy"],
}


class SandboxGovAdapter(GovAdapter):
    name = "sandbox"

    def aadhaar_send_otp(self, aadhaar):
        if not aadhaar_valid(aadhaar):
            return {"ok": False, "error": "Invalid Aadhaar number (Verhoeff checksum failed)"}
        return {"ok": True, "txn_id": "SBX-" + aadhaar[-4:], "hint": f"Sandbox OTP is {settings.SANDBOX_OTP}"}

    def aadhaar_verify_otp(self, aadhaar, otp):
        if not aadhaar_valid(aadhaar):
            return {"ok": False, "error": "Invalid Aadhaar number"}
        if otp != settings.SANDBOX_OTP:
            return {"ok": False, "error": "OTP mismatch"}
        return {"ok": True, "vid_token": "VID-" + aadhaar[-4:], "source": "UIDAI e-KYC (sandbox)"}

    def pan_verify(self, pan, name, dob=""):
        pan = pan.upper()
        if not pan_valid(pan):
            return {"ok": False, "status": "INVALID_FORMAT"}
        rec = SANDBOX_PAN.get(pan)
        if not rec:
            # Structurally valid but no record in the (sandbox) NSDL registry
            return {"ok": True, "status": "NOT_FOUND", "entity": PAN_ENTITY.get(pan[3], "?"),
                    "name_match": None, "dob_match": None, "source": "NSDL (sandbox)"}
        sim = name_similarity(name, rec["name"]) if name else None
        return {"ok": True, "status": "VALID", "entity": PAN_ENTITY.get(pan[3], "?"),
                "registered_name": rec["name"], "name_match": sim,
                "dob_match": (dob == rec["dob"]) if dob else None,
                "father_name": rec["father"], "source": "NSDL (sandbox)"}

    def mca_lookup(self, cin):
        parsed = parse_cin(cin)
        if not parsed:
            return {"ok": False, "error": "Invalid CIN format"}
        rec = SANDBOX_MCA.get(cin.upper())
        return {"ok": True, "found": bool(rec), "parsed": parsed, "record": rec, "source": "MCA21 (sandbox)"}

    def gstin_lookup(self, gstin):
        if not gstin_valid(gstin):
            return {"ok": False, "error": "Invalid GSTIN (format/checksum)"}
        return {"ok": True, "status": "Active", "embedded_pan": gstin[2:12].upper(),
                "state_code": gstin[:2], "source": "GSTN (sandbox)"}

    def nad_verify(self, institution, degree, year, name):
        key = (institution.lower().strip(), degree.lower().strip())
        names = SANDBOX_NAD.get(key)
        if names is None:
            return {"ok": True, "found": False, "source": "NAD/DigiLocker (sandbox)"}
        return {"ok": True, "found": name.lower().strip() in names, "source": "NAD/DigiLocker (sandbox)"}

    def epfo_headcount(self, company_name):
        return {"ok": True, "headcount": SANDBOX_EPFO.get(company_name.lower().strip()),
                "source": "EPFO (sandbox)"}

    def domain_age_years(self, domain):
        return SANDBOX_DOMAIN_AGE_YEARS.get(domain.lower())


def get_gov_adapter() -> SandboxGovAdapter:
    # Production: return DigiLockerAdapter(...) etc. based on settings.GOV_ADAPTER_MODE
    return SandboxGovAdapter()
