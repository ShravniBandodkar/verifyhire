"""Relational data model (PostgreSQL in production, SQLite for local dev)."""
from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core.db import Base


def _id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    # candidate | employer_admin | recruiter | admin
    role: Mapped[str] = mapped_column(String(32), index=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    profile = relationship("CandidateProfile", back_populates="user", uselist=False)
    company = relationship("Company", foreign_keys=[company_id])


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    dob: Mapped[str] = mapped_column(String(16), default="")
    father_name: Mapped[str] = mapped_column(String(255), default="")
    headline: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    years_experience: Mapped[float] = mapped_column(Float, default=0)
    current_ctc_lpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_ctc_lpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    ctc_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)   # [{degree, institution, year, verified}]
    experience: Mapped[list] = mapped_column(JSON, default=list)  # [{company, title, start, end, verified}]
    # Identity — never the raw Aadhaar number (UIDAI vault norms)
    aadhaar_masked: Mapped[str] = mapped_column(String(32), default="")
    aadhaar_token: Mapped[str] = mapped_column(String(64), default="")
    aadhaar_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    pan_masked: Mapped[str] = mapped_column(String(16), default="")
    pan_hash: Mapped[str] = mapped_column(String(64), default="")
    pan_sealed: Mapped[str] = mapped_column(Text, default="")  # AES-GCM sealed full PAN (envelope-encrypted)
    pan_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    degree_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    experience_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    trust_score: Mapped[int] = mapped_column(Integer, default=0)
    trust_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    standardized_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    open_to_work: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="profile")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # aadhaar | pan | resume | degree | experience_letter | payslip | photo | company_pan | other
    doc_type: Mapped[str] = mapped_column(String(32), default="other")
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255))
    wrapped_dek: Mapped[str] = mapped_column(Text)
    kek_version: Mapped[str] = mapped_column(String(16))
    # pending | processing | verified | flagged | rejected
    status: Mapped[str] = mapped_column(String(16), default="pending")
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)
    forensics: Mapped[dict] = mapped_column(JSON, default=dict)
    badge: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(255))
    pan: Mapped[str] = mapped_column(String(16), default="")
    cin: Mapped[str] = mapped_column(String(32), default="")
    gstin: Mapped[str] = mapped_column(String(32), default="")
    domain: Mapped[str] = mapped_column(String(255), default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    revenue_bracket: Mapped[str] = mapped_column(String(64), default="")
    headcount: Mapped[int] = mapped_column(Integer, default=0)
    vertical: Mapped[str] = mapped_column(String(128), default="")
    incorporation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    signatory_name: Mapped[str] = mapped_column(String(255), default="")
    # pending | approved | flagged | rejected
    kyb_status: Mapped[str] = mapped_column(String(16), default="pending")
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    kyb_report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    raw_prompt: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    location: Mapped[str] = mapped_column(String(64), default="")
    min_exp: Mapped[float] = mapped_column(Float, default=0)
    max_exp: Mapped[float] = mapped_column(Float, default=30)
    ctc_min_lpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    ctc_max_lpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_trust: Mapped[int] = mapped_column(Integer, default=0)
    require_pan: Mapped[bool] = mapped_column(Boolean, default=False)
    require_degree: Mapped[bool] = mapped_column(Boolean, default=False)
    min_refs: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    company = relationship("Company")


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    outreach_draft: Mapped[str] = mapped_column(Text, default="")
    # suggested | shortlisted | archived | interview
    status: Mapped[str] = mapped_column(String(16), default="suggested")
    interview_at: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Reference(Base):
    __tablename__ = "references"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    company: Mapped[str] = mapped_column(String(255), default="")
    relationship_: Mapped[str] = mapped_column("relationship", String(64), default="manager")
    token_hash: Mapped[str] = mapped_column(String(64), default="")
    # sent | verified | declined | flagged
    status: Mapped[str] = mapped_column(String(16), default="sent")
    feedback: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    respondent_ip: Mapped[str] = mapped_column(String(64), default="")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AccessGrant(Base):
    """Consent record: an employer asks, the candidate grants (time-bound) or denies/revokes."""
    __tablename__ = "access_grants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    doc_types: Mapped[list] = mapped_column(JSON, default=list)
    reveal_identity_numbers: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    # pending | granted | denied | revoked | expired
    status: Mapped[str] = mapped_column(String(16), default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    company = relationship("Company")


class AuditEvent(Base):
    """Append-only, hash-chained ledger. Each row commits to the previous row's hash."""
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    actor_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))  # user | agent | system
    action: Mapped[str] = mapped_column(String(64), index=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, default="")  # whose data
    target: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    decision: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="info")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | agent
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)


class SecurityBlock(Base):
    __tablename__ = "security_blocks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    key: Mapped[str] = mapped_column(String(128), index=True)  # ip:<x> or user:<id>
    reason: Mapped[str] = mapped_column(Text)
    until: Mapped[datetime] = mapped_column(DateTime)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
