from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ..agents import orchestrator
from ..core import ledger
from ..core.db import get_db
from ..core.security import create_token, get_current_user, hash_password, verify_password
from ..models import CandidateProfile, Company, User

router = APIRouter(prefix="/auth", tags=["Auth"])


class CandidateSignup(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=2)
    city: str = ""
    phone: str = ""


class EmployerSignup(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    company_name: str
    pan: str
    cin: str = ""
    gstin: str = ""
    domain: str = ""
    website: str = ""
    revenue_bracket: str = ""
    headcount: int = 0
    vertical: str = ""
    incorporation_year: int | None = None
    locations: list[str] = []


class Login(BaseModel):
    email: EmailStr
    password: str


def _token_response(u: User) -> dict:
    return {"access_token": create_token(u.id, u.role), "token_type": "bearer", "user": user_out(u)}


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "company_id": u.company_id}


@router.post("/register/candidate", summary="Register a candidate")
def register_candidate(body: CandidateSignup, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=body.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    u = User(email=body.email.lower(), password_hash=hash_password(body.password), full_name=body.full_name, role="candidate")
    db.add(u); db.flush()
    db.add(CandidateProfile(user_id=u.id, city=body.city, phone=body.phone))
    db.commit()
    ledger.record(db, u.id, "user.register", subject_id=u.id, details={"role": "candidate"})
    return _token_response(u)


@router.post("/register/employer", summary="Register an employer; KYB agent runs automatically")
def register_employer(body: EmployerSignup, bg: BackgroundTasks, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=body.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    co = Company(name=body.company_name, pan=body.pan.upper(), cin=body.cin.upper(), gstin=body.gstin.upper(),
                 domain=(body.domain or body.email.split("@")[-1]).lower(), website=body.website,
                 revenue_bracket=body.revenue_bracket, headcount=body.headcount, vertical=body.vertical,
                 incorporation_year=body.incorporation_year, locations=body.locations, signatory_name=body.full_name)
    db.add(co); db.flush()
    u = User(email=body.email.lower(), password_hash=hash_password(body.password), full_name=body.full_name,
             role="employer_admin", company_id=co.id)
    db.add(u); db.commit()
    ledger.record(db, u.id, "company.register", target=f"company:{co.id}", details={"name": co.name})
    bg.add_task(orchestrator.bg_kyb, co.id)
    return _token_response(u)


@router.post("/login", summary="Login and receive a JWT")
def login(body: Login, db: Session = Depends(get_db)):
    u = db.query(User).filter_by(email=body.email.lower()).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    ledger.record(db, u.id, "user.login", subject_id=u.id if u.role == "candidate" else "")
    return _token_response(u)


@router.get("/me", summary="Current user")
def me(user: User = Depends(get_current_user)):
    return user_out(user)
