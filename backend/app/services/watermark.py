"""Dynamic server-side watermarking: every vault view is stamped with viewer, company, time and
audit sequence number, so leaked copies are traceable to the exact view event."""
import io

from PIL import Image, ImageDraw, ImageFont


def _font(size: int):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def watermark_image(data: bytes, label: str) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    size = max(14, img.width // 28)
    f = _font(size)
    step_y = size * 5
    for y in range(-img.height, img.height * 2, step_y):
        d.text((0, y), ("   " + label) * 6, font=f, fill=(200, 30, 30, 70))
    layer = layer.rotate(25, expand=False)
    out = Image.alpha_composite(img, layer).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def watermark_pdf(data: bytes, label: str) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for page in reader.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(w, h))
        c.setFillColor(Color(0.8, 0.1, 0.1, alpha=0.18))
        c.setFont("Helvetica-Bold", 14)
        c.saveState()
        c.translate(w / 2, h / 2)
        c.rotate(30)
        for i in range(-12, 13):
            c.drawCentredString(0, i * 48, label)
        c.restoreState()
        c.save()
        buf.seek(0)
        wp = writer.add_page(page)
        wp.merge_page(PdfReader(buf).pages[0])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def watermark(data: bytes, mime: str, label: str) -> tuple[bytes, str]:
    if mime == "application/pdf":
        return watermark_pdf(data, label), mime
    if mime.startswith("image/"):
        return watermark_image(data, label), "image/jpeg"
    return data, mime
