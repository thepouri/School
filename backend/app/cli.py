"""Admin CLI — create the first admin account (or reset its password).

Usage:
    python -m app.cli create-admin admin@example.com s3cret [--days 365]
"""
import argparse
import asyncio

from app.adapters.db.bootstrap import ensure_auth_schema
from app.adapters.db.pool import create_pool
from app.core.config import settings
from app.core.security import hash_password


async def create_admin(email: str, password: str, days: int) -> None:
    pool = await create_pool()
    try:
        await ensure_auth_schema(pool)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO app.accounts (email, password_hash, is_admin, expires_at)
                VALUES ($1, $2, true, now() + make_interval(days => $3))
                ON CONFLICT (email) DO UPDATE
                  SET password_hash = EXCLUDED.password_hash,
                      is_admin = true,
                      is_active = true,
                      expires_at = GREATEST(app.accounts.expires_at,
                                            now() + make_interval(days => $3))
                RETURNING id, email, expires_at
                """,
                email, hash_password(password), days,
            )
        print(f"[admin] ok: id={row['id']} email={row['email']} expires={row['expires_at']}")
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Skool Explorer API admin CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin", help="create/update the admin account")
    p.add_argument("email")
    p.add_argument("password")
    p.add_argument("--days", type=int, default=3650)
    args = parser.parse_args()
    if args.cmd == "create-admin":
        asyncio.run(create_admin(args.email.strip(), args.password, max(1, min(args.days, 3650))))


if __name__ == "__main__":
    main()
