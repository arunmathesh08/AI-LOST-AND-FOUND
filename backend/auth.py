import os
import hashlib
import hmac
import jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import User

SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-lost-and-found-hackathon-token-key-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Salted SHA-256 password hash for fast, dependency-stable hashing."""
    salt = "hackathon_salt_salt"
    pwd_bytes = (password + salt).encode("utf-8")
    return hashlib.sha256(pwd_bytes).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hmac.compare_digest(hash_password(plain_password), hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials.strip() if credentials.credentials else ""

    # 1. Direct Demo Token handling
    if token in ["demo-token-1", "demo1", "demo1@example.com"]:
        user = db.query(User).filter(User.email == "demo1@example.com").first()
        if not user:
            user = User(name="Demo User One", email="demo1@example.com", password_hash=hash_password("Demo@12345"), role="user")
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    if token in ["demo-token-2", "demo2", "demo2@example.com"]:
        user = db.query(User).filter(User.email == "demo2@example.com").first()
        if not user:
            user = User(name="Demo User Two", email="demo2@example.com", password_hash=hash_password("Demo@12345"), role="user")
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    # 2. Local HS256 JWT decoding
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id:
            user = db.query(User).filter(User.id == int(user_id)).first()
            if user:
                return user
    except Exception:
        pass

    # 3. Supabase / External JWT unverified payload decoding
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        email = unverified.get("email")
        if email:
            user = db.query(User).filter(User.email == email.lower().strip()).first()
            if not user:
                name = unverified.get("user_metadata", {}).get("name") or email.split("@")[0]
                user = User(name=name, email=email.lower().strip(), password_hash=hash_password("SupabaseAuth123!"), role="user")
                db.add(user)
                db.commit()
                db.refresh(user)
            if user:
                return user
    except Exception:
        pass

    # 4. Fallback for sb-session or generic demo token
    if "demo" in token.lower() or "sb-" in token.lower():
        user = db.query(User).filter(User.email == "demo1@example.com").first()
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user
