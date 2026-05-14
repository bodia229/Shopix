import os
import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone

SECRET = os.getenv("SECRET_KEY", "shopix-secret-dev-key-change-in-prod")
ALGO   = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    return jwt.encode({"sub": str(user_id), "exp": exp}, SECRET, algorithm=ALGO)


def get_current_user(token: str | None, db):
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGO])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
    import models
    return db.query(models.User).filter(models.User.id == user_id).first()
