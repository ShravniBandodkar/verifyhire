"""VerifyHire API — FastAPI application entrypoint."""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agents import devsecops
from .api import auth, candidate, employer, platform
from .core.config import settings
from .core.db import Base, SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DESCRIPTION = """
**VerifyHire** — AI-native verified resume registry & employer talent cloud.

* Authenticate with `POST /api/v1/auth/login` and send `Authorization: Bearer <token>`,
  or create an API key at `POST /api/v1/developer/keys` and send `X-API-Key: <key>`.
* Seven autonomous agents run behind these endpoints; every decision is written to an
  immutable hash-chained ledger (`/api/v1/admin/ledger/verify`).
* Government integrations run in **sandbox** mode (Aadhaar OTP is `123456`).
"""

@asynccontextmanager
async def lifespan(_app):
    startup()
    yield


app = FastAPI(title="VerifyHire API", version="1.0.0", description=DESCRIPTION, lifespan=lifespan,
              docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")

app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Audit-Seq"])

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self' 'unsafe-inline'; connect-src 'self' *; media-src 'self' blob:; frame-src 'self' blob:; object-src 'self' blob:; frame-ancestors 'none'")


@app.middleware("http")
async def security_and_telemetry(request: Request, call_next):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    actor = f"ip:{ip}"
    is_api = request.url.path.startswith("/api/")
    if is_api:
        if devsecops.TELEMETRY.is_blocked(actor):
            return JSONResponse({"detail": "Temporarily blocked by the security agent"}, status_code=429)
        if devsecops.TELEMETRY.rate(actor) > settings.RATE_LIMIT_PER_MIN:
            db = SessionLocal()
            try:
                devsecops.block(db, actor, f"Rate limit exceeded ({settings.RATE_LIMIT_PER_MIN}/min)", minutes=5)
            finally:
                db.close()
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    if is_api:
        route = request.scope.get("route")
        devsecops.TELEMETRY.record(actor, getattr(route, "path", request.url.path), ms, response.status_code)
    response.headers["X-Response-Time-ms"] = f"{ms:.1f}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
    if not request.url.path.startswith(("/docs", "/redoc")):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Frame-Options"] = "DENY"
    # Pages must always be re-checked so a new deploy never pairs old HTML with deleted CSS/JS files;
    # hashed build assets never change, so they can be cached for a year.
    path = request.url.path
    if path.startswith("/_next/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path in ("/sw.js", "/manifest.json") or response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


API = "/api/v1"
for r in (auth.router, candidate.router, employer.router, platform.router):
    app.include_router(r, prefix=API)


@app.get("/api/health", tags=["Platform"])
def health():
    return {"status": "ok", "env": settings.ENV}


def startup():
    Base.metadata.create_all(engine)
    if settings.AUTO_SEED:
        from .seed import seed
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()
    # Warm the vector index from persisted embeddings (in-memory backend is per-process)
    from .models import CandidateProfile
    from .services.embeddings import index
    db = SessionLocal()
    try:
        for p in db.query(CandidateProfile).all():
            if p.embedding:
                index().upsert(p.user_id, p.embedding)
    finally:
        db.close()
    devsecops.patrol_loop(SessionLocal, interval=120)


# ---------- Serve the static Next.js build (single-service deploy) ----------
FRONT = Path(__file__).resolve().parent.parent / settings.FRONTEND_DIR
SAMPLES = Path(__file__).resolve().parent.parent / "sample_docs"

if SAMPLES.exists():
    app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")

if FRONT.exists():
    app.mount("/_next", StaticFiles(directory=FRONT / "_next"), name="next-static")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        for cand in (FRONT / full_path, FRONT / f"{full_path}.html", FRONT / full_path / "index.html"):
            if cand.is_file():
                return FileResponse(cand)
        return FileResponse(FRONT / "index.html")
