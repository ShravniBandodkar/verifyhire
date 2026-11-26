from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings

_url = settings.DATABASE_URL
if _url.startswith("postgres://"):  # Render gives postgres:// URLs
    _url = _url.replace("postgres://", "postgresql://", 1)

IS_POSTGRES = _url.startswith("postgresql")
engine = create_engine(
    _url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
