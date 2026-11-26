"""Document text extraction (PDF / DOCX / images via Tesseract OCR) and image forensics helpers."""
import io
import logging
import re
import zipfile

from PIL import Image, ImageChops, ImageStat

log = logging.getLogger("docs")


def sniff_mime(filename: str, data: bytes) -> str:
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"PK\x03\x04":
        if filename.lower().endswith(".docx"):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return "application/zip"
    if filename.lower().endswith((".txt", ".md")):
        return "text/plain"
    return "application/octet-stream"


def pdf_info(data: bytes) -> dict:
    from pypdf import PdfReader
    out = {"text": "", "pages": 0, "producer": "", "creator": "", "fonts": [], "created": "", "modified": ""}
    try:
        r = PdfReader(io.BytesIO(data))
        out["pages"] = len(r.pages)
        out["text"] = "\n".join((p.extract_text() or "") for p in r.pages)[:20000]
        meta = r.metadata or {}
        out["producer"] = str(meta.get("/Producer", "") or "")
        out["creator"] = str(meta.get("/Creator", "") or "")
        out["created"] = str(meta.get("/CreationDate", "") or "")
        out["modified"] = str(meta.get("/ModDate", "") or "")
        fonts = set()
        for p in r.pages:
            res = p.get("/Resources") or {}
            f = res.get("/Font") if hasattr(res, "get") else None
            if f:
                for k in f:
                    try:
                        fonts.add(str(f[k].get_object().get("/BaseFont", k)))
                    except Exception:
                        fonts.add(str(k))
        out["fonts"] = sorted(fonts)
    except Exception as e:
        log.warning("pdf parse failed: %s", e)
    return out


def docx_text(data: bytes) -> str:
    try:
        import docx
        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)[:20000]
    except Exception as e:
        log.warning("docx parse failed: %s", e)
        return ""


def ocr_image(data: bytes) -> str:
    try:
        import pytesseract
        img = Image.open(io.BytesIO(data)).convert("L")
        if img.width < 1000:
            img = img.resize((img.width * 2, img.height * 2))
        return pytesseract.image_to_string(img)[:20000]
    except Exception as e:
        log.warning("OCR unavailable/failed: %s", e)
        return ""


def extract_text(filename: str, mime: str, data: bytes) -> tuple[str, dict]:
    """Returns (text, technical metadata)."""
    if mime == "application/pdf":
        info = pdf_info(data)
        text = info.pop("text")
        if len(text.strip()) < 20:  # scanned PDF — rasterise first page isn't available w/o poppler; note it
            info["scanned"] = True
        return text, info
    if mime.endswith("wordprocessingml.document"):
        return docx_text(data), {}
    if mime.startswith("image/"):
        return ocr_image(data), image_meta(data)
    if mime == "text/plain":
        return data.decode(errors="ignore")[:20000], {}
    return "", {}


def image_meta(data: bytes) -> dict:
    out = {}
    try:
        img = Image.open(io.BytesIO(data))
        out["size"] = list(img.size)
        out["format"] = img.format
        exif = img.getexif()
        if exif:
            sw = exif.get(305)  # Software tag
            if sw:
                out["software"] = str(sw)
            dt = exif.get(306)
            if dt:
                out["exif_datetime"] = str(dt)
    except Exception:
        pass
    return out


def error_level_analysis(data: bytes) -> dict:
    """ELA: recompress JPEG at known quality; spliced/edited regions show uneven error levels."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        re_img = Image.open(io.BytesIO(buf.getvalue()))
        diff = ImageChops.difference(img, re_img).convert("L")
        w, h = diff.size
        gw, gh = max(1, w // 8), max(1, h // 8)
        cells = []
        for y in range(0, h - gh + 1, gh):
            for x in range(0, w - gw + 1, gw):
                cells.append(ImageStat.Stat(diff.crop((x, y, x + gw, y + gh))).mean[0])
        mean = sum(cells) / len(cells)
        mx = max(cells)
        ratio = (mx / mean) if mean > 0.05 else 1.0
        return {"ela_mean": round(mean, 3), "ela_max_cell": round(mx, 3), "ela_ratio": round(ratio, 2),
                "suspicious": ratio > 6 and mx > 4}
    except Exception as e:
        return {"error": str(e)}


def unzip_bundle(data: bytes, limit: int = 40) -> list[tuple[str, bytes]]:
    files = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir() or info.file_size > 15 * 1024 * 1024 or "__MACOSX" in info.filename:
                continue
            files.append((info.filename.split("/")[-1], z.read(info)))
            if len(files) >= limit:
                break
    return files


AADHAAR_RE = re.compile(r"(?<!\d)([2-9]\d{3}\s?\d{4}\s?\d{4})(?!\d)")
PAN_TXT_RE = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b")
DOB_RE = re.compile(r"(?:DOB|Date of Birth|D\.O\.B)[^0-9]{0,10}(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}-\d{2}-\d{2})", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")
CTC_RE = re.compile(r"(?:CTC|Annual\s+Compensation|Gross\s+Salary)[^0-9]{0,30}(?:INR|Rs\.?|₹)?\s?([\d,]+(?:\.\d+)?)\s*(LPA|lakhs?|L)?", re.I)
