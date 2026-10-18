"""Password hashing + JWT issuing/verification (pure functions, no I/O)."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt


def hash_password(plain: str) -> str:
    # bcrypt has a 72-byte input limit; pre-hash long secrets with sha256.
    data = plain.encode("utf-8")
    if len(data) > 72:
        import hashlib
        data = hashlib.sha256(data).hexdigest().encode("ascii")
    return bcrypt.hashpw(data, bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        data = plain.encode("utf-8")
        if len(data) > 72:
            import hashlib
            data = hashlib.sha256(data).hexdigest().encode("ascii")
        return bcrypt.checkpw(data, hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_token(secret: str, user_id: int, expires_at: datetime, days: float = 7.0) -> str:
    """Token lives min(days, until subscription expiry)."""
    exp = min(
        datetime.now(timezone.utc) + timedelta(days=days),
        expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc),
    )
    payload = {"sub": str(user_id), "exp": exp}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> int | None:
    """→ account id, or None when invalid/expired."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
