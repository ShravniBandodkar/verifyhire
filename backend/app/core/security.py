"""Authentication (JWT + API keys) and role-based access control."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(p: str) -> str:
    return pwd.hash(p)


def verify_password(p: str, h: str) -> bool:
    try:
        return pwd.verify(p, h)
    except Exception:
        return False


def create_token(user_id: str, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "role": role, "exp": exp}, settings.JWT_SECRET, algorithm="HS256")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_api_key() -> tuple[str, str, str]:
    raw = "vh_" + secrets.token_urlsafe(32)
    return raw, raw[:10], sha256(raw)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    from ..models import ApiKey, User, now

    user = None
    api_key = request.headers.get("x-api-key")
    if api_key:
        k = db.query(ApiKey).filter_by(key_hash=sha256(api_key), revoked=False).first()
        if k:
            k.last_used = now()
            db.commit()
            user = db.get(User, k.user_id)
    elif creds:
        try:
            payload = jwt.decode(creds.credentials, settings.JWT_SECRET, algorithms=["HS256"])
            user = db.get(User, payload.get("sub"))
        except JWTError:
            user = None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account blocked by security agent")
    request.state.user_id = user.id
    return user


def require_roles(*roles: str):
    def dep(user=Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(roles)}")
        return user
    return dep
