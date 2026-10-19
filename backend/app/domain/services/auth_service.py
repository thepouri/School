"""Auth service — login + per-request account resolution.

Pure orchestration: no SQL, no FastAPI types.
"""
from app.core import security


class AuthError(Exception):
    pass


class AuthService:
    def __init__(self, accounts, secret: str, token_days: float = 7.0) -> None:
        self._accounts = accounts
        self._secret = secret
        self._token_days = token_days

    async def login(self, email: str, password: str) -> dict:
        row = await self._accounts.get_by_email(email.strip())
        # Same error either way so we don't reveal which emails exist.
        if not row or not security.verify_password(password, row["password_hash"]):
            raise AuthError("Invalid email or password")
        if not row["is_active"]:
            raise AuthError("Account disabled")
        expires = row["expires_at"]
        if not isinstance(expires, str):
            from app.domain.models import _iso
            expires = _iso(expires)
        expired = _expired(row["expires_at"])
        if expired:
            raise AuthError("Subscription expired")
        token = security.create_token(
            self._secret, row["id"], row["expires_at"], days=self._token_days
        )
        return {
            "token": token,
            "account": {
                "id": row["id"],
                "email": row["email"],
                "label": row.get("label"),
                "expires_at": expires,
                "is_admin": bool(row.get("is_admin")),
            },
        }

    async def resolve(self, token: str) -> dict | None:
        """Token → fresh account row (re-checks active/expiry per request)."""
        account_id = security.decode_token(self._secret, token)
        if account_id is None:
            return None
        row = await self._accounts.get_by_id(account_id)
        if not row or not row["is_active"] or _expired(row["expires_at"]):
            return None
        return {
            "id": row["id"],
            "email": row["email"],
            "label": row.get("label"),
            "is_admin": bool(row.get("is_admin")),
        }

    async def is_admin(self, account_id: int) -> bool:
        row = await self._accounts.get_by_id(account_id)
        return bool(row and row.get("is_admin"))


def _expired(dt) -> bool:
    if dt is None:
        return True
    from datetime import datetime, timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt <= datetime.now(timezone.utc)
