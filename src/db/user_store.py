"""
User store — account persistence for BlueprintIQ.

Handles registration, login verification, plan management.
Passwords are stored as bcrypt hashes; never plain-text.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import bcrypt

import config
from src.monitoring.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store: UserStore | None = None


def get_user_store() -> UserStore:
    global _store
    if _store is None:
        _store = UserStore()
    return _store


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class UserStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = str(db_path or config.DB_PATH)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        from src.db.migrations import run_migrations
        with self._connect() as conn:
            run_migrations(conn)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def create(
        self,
        email: str,
        password: str,
        full_name: str = "",
        company: str = "",
    ) -> dict:
        """
        Create a new user. Raises ValueError if email already exists.
        Returns the user dict (no password_hash).
        """
        email = email.strip().lower()
        if self.get_by_email(email):
            raise ValueError(f"Email already registered: {email}")

        user_id = str(uuid.uuid4())
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, full_name, company)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, email, hashed, full_name.strip(), company.strip()),
            )
            conn.commit()

        log.info("New user registered: %s", email)
        return self.get_by_id(user_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_by_email(self, email: str) -> dict | None:
        email = email.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
        return _safe(row)

    def get_by_id(self, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return _safe(row)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def verify_password(self, email: str, password: str) -> dict | None:
        """
        Verify email + password. Returns user dict on success, None on failure.
        Never leaks which field was wrong.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
            ).fetchone()

        if not row:
            # Constant-time dummy check to prevent timing attacks
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
            return None

        stored = dict(row)
        if not bcrypt.checkpw(password.encode(), stored["password_hash"].encode()):
            return None
        stored.pop("password_hash", None)
        return stored

    # ------------------------------------------------------------------
    # Plan management
    # ------------------------------------------------------------------

    def set_plan(
        self,
        user_id: str,
        plan: str,
        stripe_customer_id: str | None = None,
    ) -> None:
        """Upgrade/downgrade user plan. Resets credits based on plan."""
        credits = {"free": 1, "pro": 9999, "agency": 9999}.get(plan, 1)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET plan = ?, credits = ?,
                    stripe_customer_id = COALESCE(?, stripe_customer_id)
                WHERE id = ?
                """,
                (plan, credits, stripe_customer_id, user_id),
            )
            conn.commit()
        log.info("User %s plan updated to %s", user_id, plan)

    def decrement_credit(self, user_id: str) -> bool:
        """
        Consume one review credit. Returns True if credit was available,
        False if the user is out of credits.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT credits, plan FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not row:
                return False
            if row["plan"] in ("pro", "agency"):
                return True  # unlimited
            if row["credits"] <= 0:
                return False
            conn.execute(
                "UPDATE users SET credits = credits - 1 WHERE id = ?",
                (user_id,),
            )
            conn.commit()
        return True

    def list_recent(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_safe(r) for r in rows]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(row: sqlite3.Row | None) -> dict | None:
    """Convert Row to dict, stripping password_hash."""
    if row is None:
        return None
    d = dict(row)
    d.pop("password_hash", None)
    return d
