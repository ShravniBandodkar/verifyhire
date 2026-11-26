"""Generates SYNTHETIC sample KYC documents for demos (no real identities).

Creates clean documents for the demo candidate plus deliberately tampered ones so the
forensics agent can be shown catching them.
"""
import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .services.gov import verhoeff_digit

OUT = Path(__file__).resolve().parent.parent / "sample_docs"

DEMO = {"name": "Aisha Kapoor", "dob": "14/03/1997", "father": "Vikram Kapoor", "pan": "ABCPK1234K"}
AADHAAR_BASE = "52741896330"
AADHAAR = AADHAAR_BASE + verhoeff_digit(AADHAAR_BASE)


def _font(sz, bold=False):
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for d in ["/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/"]:
        for n in names:
            try:
                return ImageFont.truetype(d + n, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def card(lines: list[tuple[str, int, bool]], header: str, color) -> bytes:
    img = Image.new("RGB", (1300, 820), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1300, 130], fill=color)
    d.text((40, 35), header, font=_font(52, True), fill="white")
    d.rectangle([60, 200, 330, 520], outline="gray", width=4)
    d.text((120, 340), "PHOTO", font=_font(36), fill="gray")
    y = 190
    for text, sz, bold in lines:
        d.text((380, y), text, font=_font(sz, bold), fill="black")
        y += sz + 34
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def pan_card(name=DEMO["name"], father=DEMO["father"], dob=DEMO["dob"], pan=DEMO["pan"]) -> bytes:
    return card([("INCOME TAX DEPARTMENT", 40, True), ("Permanent Account Number", 34, False), (pan, 56, True),
                 ("Name", 30, False), (name.upper(), 42, True), ("Father's Name", 30, False), (father.upper(), 40, True),
                 (f"Date of Birth {dob}", 36, False)], "GOVT. OF INDIA", (20, 60, 140))


def aadhaar_card(name=DEMO["name"], dob=DEMO["dob"], number=AADHAAR) -> bytes:
    n = f"{number[:4]} {number[4:8]} {number[8:]}"
    return card([("Unique Identification Authority of India", 30, False), (name, 46, True), (f"DOB: {dob}", 40, False),
                 ("FEMALE", 38, False), (n, 64, True), ("Aadhaar - Aam Aadmi ka Adhikar", 28, False)],
                "GOVERNMENT OF INDIA", (200, 90, 20))


def _pdf(lines: list[tuple[str, int]], producer="VerifyHire Sample Generator", fonts=None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setProducer(producer)
    c.setCreator(producer)
    y = 780
    fonts = fonts or ["Helvetica"]
    for i, (t, sz) in enumerate(lines):
        c.setFont(fonts[i % len(fonts)], sz)
        c.drawString(60, y, t)
        y -= sz + 14
    c.save()
    return buf.getvalue()


def degree_pdf(name=DEMO["name"], tamper=False) -> bytes:
    lines = [("ANNA UNIVERSITY", 26), ("Chennai, Tamil Nadu", 14), ("", 10),
             ("This is to certify that", 16), (f"certify that {name} has been awarded", 16),
             ("the degree of Bachelor of Engineering in Computer Science", 16),
             ("with First Class with Distinction at the convocation held in 2018.", 14), ("", 10),
             ("Registration No. 2014CS0457      Year 2018", 12), ("Controller of Examinations", 12)]
    if tamper:
        return _pdf(lines, producer="Adobe Photoshop CC 2024",
                    fonts=["Helvetica", "Times-Roman", "Courier", "Helvetica-Bold", "Times-Bold", "Courier-Bold", "Helvetica-Oblique"])
    return _pdf(lines)


def experience_pdf(name=DEMO["name"]) -> bytes:
    return _pdf([("Nimbus Cloudworks Private Limited", 22), ("No. 42, Outer Ring Road, Bengaluru 560103", 11), ("", 10),
                 ("RELIEVING & EXPERIENCE LETTER", 18), ("To whom it may concern,", 13),
                 (f"This is to certify that {name} worked with us as a Software Engineer", 13),
                 ("from 01 Jul 2019 to 30 Jun 2024. She was relieved from her duties on 30 Jun 2024.", 13),
                 ("During her tenure her conduct was excellent.", 13), ("", 10), ("For Nimbus Cloudworks Private Limited", 12),
                 ("Head - People Operations", 12)])


def payslip_pdf(name=DEMO["name"]) -> bytes:
    return _pdf([("Nimbus Cloudworks Private Limited", 20), ("PAYSLIP - May 2024", 16), (f"Employee: {name}   Emp ID: NCW-1182", 12),
                 ("PAN: XXXXX (redacted)   Bank A/c: XXXX (redacted)", 12), ("", 8),
                 ("Basic 75,000    HRA 30,000    Special 40,000", 12), ("Gross Salary 1,45,000", 13),
                 ("Annual CTC INR 18.5 LPA", 13), ("Net Pay 1,21,300", 12)])


def resume_pdf(name=DEMO["name"]) -> bytes:
    return _pdf([(name, 24), ("Bengaluru | aisha.kapoor@demo.example | +91 9876543210", 11), ("", 8),
                 ("SUMMARY", 14), ("Full-stack engineer with 5 years experience building cloud-native SaaS.", 11), ("", 6),
                 ("SKILLS", 14), ("React, TypeScript, Node.js, Python, FastAPI, PostgreSQL, AWS, Docker, Kubernetes, LangChain, RAG", 11), ("", 6),
                 ("EXPERIENCE", 14), ("Software Engineer - Nimbus Cloudworks Private Limited (Jul 2019 - Jun 2024)", 11),
                 ("Built microservices and React dashboards serving 2M users.", 10), ("", 6),
                 ("EDUCATION", 14), ("B.E. Computer Science - Anna University (2018)", 11),
                 ("M.Tech Software Systems - BITS Pilani (2023)", 11)])


def tampered_pan() -> bytes:
    """Splice: paste a different PAN number patch with a different JPEG history onto the card."""
    base = Image.open(io.BytesIO(pan_card())).convert("RGB")
    patch = Image.new("RGB", (520, 80), (250, 250, 250))
    d = ImageDraw.Draw(patch)
    d.text((4, 2), "ABCPK9999Z", font=_font(60, True), fill=(10, 10, 10))
    b = io.BytesIO(); patch.save(b, "JPEG", quality=35)
    patch = Image.open(io.BytesIO(b.getvalue()))
    base.paste(patch, (378, 300))
    out = io.BytesIO()
    exif = base.getexif(); exif[305] = "Adobe Photoshop 25.1"
    base.save(out, "JPEG", quality=95, exif=exif)
    return out.getvalue()


def generate() -> Path:
    OUT.mkdir(exist_ok=True)
    clean = {"aisha_pan_card.jpg": pan_card(), "aisha_aadhaar_card.jpg": aadhaar_card(), "aisha_degree.pdf": degree_pdf(),
             "aisha_experience_letter.pdf": experience_pdf(), "aisha_payslip.pdf": payslip_pdf(), "aisha_resume.pdf": resume_pdf()}
    bad = {"TAMPERED_degree_photoshop.pdf": degree_pdf(tamper=True), "TAMPERED_pan_spliced.jpg": tampered_pan()}
    for n, b in {**clean, **bad}.items():
        (OUT / n).write_bytes(b)
    with zipfile.ZipFile(OUT / "aisha_kyc_bundle.zip", "w") as z:
        for n, b in clean.items():
            z.writestr(n, b)
    (OUT / "README.txt").write_text(
        "SYNTHETIC demo documents — not real identities.\n"
        f"Demo login: aisha@demo.example / Candidate@123\nAadhaar (sandbox, Verhoeff-valid): {AADHAAR}  OTP: 123456\n"
        "Drag aisha_kyc_bundle.zip onto the Vault to see agents classify & verify everything.\n"
        "TAMPERED_* files show the forensics agent catching edits.\n")
    return OUT


if __name__ == "__main__":
    print(generate())
