"""Unit tests for the deterministic guardrails the agents rely on."""
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP}/u.db")
os.environ.setdefault("STORAGE_DIR", f"{TMP}/store")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.base import sign_badge, verify_badge  # noqa: E402
from app.agents.kyc_forensics import classify_text, parse_fields  # noqa: E402
from app.agents.talent_matchmaker import parse_query  # noqa: E402
from app.core import vault  # noqa: E402
from app.services.gov import aadhaar_valid, gstin_checksum, gstin_valid, pan_valid, parse_cin, verhoeff_digit  # noqa: E402


def test_aadhaar_verhoeff():
    base = "52741896330"
    good = base + verhoeff_digit(base)
    assert aadhaar_valid(good)
    assert not aadhaar_valid(good[:-1] + str((int(good[-1]) + 1) % 10))
    assert not aadhaar_valid("123456789012")  # cannot start with 1


def test_pan_gstin_cin():
    assert pan_valid("ABCPK1234K") and not pan_valid("ABCXK1234K") and not pan_valid("ABC1K1234K")
    g = "29AAACN4455F1Z"
    assert gstin_valid(g + gstin_checksum(g)) and not gstin_valid(g + "0" if gstin_checksum(g) != "0" else g + "1")
    assert parse_cin("U72200KA2014PTC074512")["year"] == 2014 and parse_cin("BAD") is None


def test_masking_and_tokens():
    assert vault.mask_aadhaar("5274 1896 3301") == "XXXX-XXXX-3301"
    assert vault.mask_pan("ABCPK1234K") == "ABXXXXX34K"
    assert vault.tokenize("527418963301", "aadhaar") == vault.tokenize("527418963301", "aadhaar")
    assert vault.tokenize("527418963301", "aadhaar") != vault.tokenize("527418963301", "pan")


def test_envelope_encryption_roundtrip_and_rotation():
    blob = vault.put(b"secret degree", "owner1")
    assert vault.get(blob.key, blob.wrapped_dek, blob.kek_version, "owner1") == b"secret degree"
    try:
        vault.get(blob.key, blob.wrapped_dek, blob.kek_version, "someone-else")
        assert False, "AAD must bind ciphertext to owner"
    except Exception:
        pass
    vault.add_kek("vtest")
    rew = vault.rewrap(blob.wrapped_dek, blob.kek_version, "vtest")
    assert vault.get(blob.key, rew, "vtest", "owner1") == b"secret degree"
    sealed = vault.seal_field("ABCPK1234K", "o2")
    assert vault.open_field(vault.reseal_field(sealed, "vtest"), "o2") == "ABCPK1234K"


def test_badges_are_tamper_evident():
    b = sign_badge({"doc_id": "x", "verdict": "verified"})
    assert verify_badge(b)["doc_id"] == "x"
    body, sig = b.rsplit(".", 1)
    assert verify_badge(body + "." + ("0" * len(sig))) is None


def test_ledger_detects_tampering():
    from app.core import ledger
    from app.core.db import Base, SessionLocal, engine
    from app.models import AuditEvent
    Base.metadata.create_all(engine)
    db = SessionLocal()
    for i in range(5):
        ledger.record(db, "u1", "test.event", details={"i": i})
    assert ledger.verify_chain(db)["valid"]
    ev = db.query(AuditEvent).order_by(AuditEvent.seq).all()[2]
    ev.details = {"i": 999}
    db.commit()
    res = ledger.verify_chain(db)
    assert not res["valid"] and res["broken_at_seq"] == ev.seq
    db.close()


def test_classifier_and_parsers():
    assert classify_text("x.jpg", "INCOME TAX DEPARTMENT Permanent Account Number", "image/jpeg") == "pan"
    assert classify_text("x.pdf", "This is to certify ... has been awarded the degree of", "application/pdf") == "degree"
    assert parse_fields("payslip", "Gross Salary 1,45,000\nAnnual CTC INR 18.5 LPA")["ctc_lpa"] == 18.5
    f = parse_fields("pan", "INCOME TAX DEPARTMENT\nABCPK1234K\nName\nAISHA KAPOOR\nFather's Name\nVIKRAM KAPOOR\nDate of Birth 14/03/1997")
    assert f["pan_number"] == "ABCPK1234K" and f["name"] == "AISHA KAPOOR" and f["dob"] == "1997-03-14"


def test_nl_query_parser():
    f = parse_query("PAN-verified React devs in Bangalore, 3-5 yrs, under 25 LPA, at least two verified references, trust above 70")
    assert f["city"] == "bengaluru" and f["min_exp"] == 3 and f["max_exp"] == 5 and f["ctc_max"] == 25
    assert f["pan_verified"] and f["min_refs"] == 2 and f["min_trust"] == 70 and "react" in f["skills"]
