"""PostgreSQL AccountRepository — implements ports.AccountRepository."""
import asyncpg

from app.adapters.db.pool import record_to_dict


class PgAccountRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_by_email(self, email: str) -> dict | None:
        sql = """
            SELECT id, email, password_hash, label, is_admin, is_active, expires_at
            FROM app.accounts WHERE lower(email) = lower($1)
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, email)
        return record_to_dict(row) if row else None

    async def get_by_id(self, account_id: int) -> dict | None:
        sql = """
            SELECT id, email, password_hash, label, is_admin, is_active, expires_at
            FROM app.accounts WHERE id = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, account_id)
        return record_to_dict(row) if row else None

    # --- admin management (used by the admin router) -------------------

    async def list_accounts(self) -> list[dict]:
        sql = """
            SELECT a.id, a.email, a.label, a.is_active, a.expires_at, a.created_at,
                   count(u.id)::int AS requests_30d
            FROM app.accounts a
            LEFT JOIN app.usage_log u
              ON u.account_id = a.id AND u.created_at > now() - interval '30 days'
            GROUP BY a.id ORDER BY a.id
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return [record_to_dict(r) for r in rows]

    async def create_account(
        self, email: str, password: str, label: str | None, days: int
    ) -> dict:
        from app.core.security import hash_password
        sql = """
            INSERT INTO app.accounts (email, password_hash, label, expires_at)
            VALUES ($1, $2, $3, now() + make_interval(days => $4))
            RETURNING id, email, label, is_active, expires_at, created_at
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, email, hash_password(password), label, days)
        return record_to_dict(row)

    async def extend(self, account_id: int, days: int) -> dict | None:
        """Renewal: push expiry forward from max(now, current expiry)."""
        sql = """
            UPDATE app.accounts
            SET expires_at = GREATEST(expires_at, now()) + make_interval(days => $2)
            WHERE id = $1
            RETURNING id, email, label, is_active, expires_at, created_at
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, account_id, days)
        return record_to_dict(row) if row else None

    async def set_active(self, account_id: int, is_active: bool) -> dict | None:
        sql = """
            UPDATE app.accounts SET is_active = $2
            WHERE id = $1
            RETURNING id, email, label, is_active, expires_at, created_at
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, account_id, is_active)
        return record_to_dict(row) if row else None

    async def set_password(self, account_id: int, password: str) -> None:
        from app.core.security import hash_password
        sql = "UPDATE app.accounts SET password_hash = $2 WHERE id = $1"
        async with self._pool.acquire() as conn:
            await conn.execute(sql, account_id, hash_password(password))

    async def delete(self, account_id: int) -> bool:
        """Hard delete; usage_log rows cascade via FK. → True when a row went."""
        sql = "DELETE FROM app.accounts WHERE id = $1"
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, account_id)
        return status == "DELETE 1"
