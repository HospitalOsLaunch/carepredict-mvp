"""SQLite storage for accounts, sessions, one-time tokens, audit trail and per-account journals.

One file per environment (a Docker volume in staging/production). Schema changes are applied at
start-up by
ordered migrations recorded in ``schema_version``; a migration never rewrites history silently.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from . import security

Role = Literal["admin", "pilot"]
Status = Literal["invited", "active", "disabled"]
TokenKind = Literal["invite", "reset"]
Clock = Callable[[], datetime]

MIGRATIONS: list[str] = [
    # 1 — accounts, sessions, one-time tokens, login failures, audit trail, journals
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        public_id TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT,
        role TEXT NOT NULL CHECK (role IN ('admin', 'pilot')),
        status TEXT NOT NULL CHECK (status IN ('invited', 'active', 'disabled')),
        display_name TEXT NOT NULL DEFAULT '',
        job_title TEXT NOT NULL DEFAULT '',
        establishment TEXT NOT NULL DEFAULT '',
        default_unit TEXT NOT NULL DEFAULT '',
        analytics_consent INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_login_at TEXT
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        user_agent TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX sessions_user ON sessions(user_id);
    CREATE TABLE one_time_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('invite', 'reset')),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT
    );
    CREATE TABLE login_failures (
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL,
        ip TEXT NOT NULL,
        at TEXT NOT NULL
    );
    CREATE INDEX login_failures_email ON login_failures(email, at);
    CREATE INDEX login_failures_ip ON login_failures(ip, at);
    CREATE TABLE audit (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        actor_id INTEGER,
        action TEXT NOT NULL,
        target_id INTEGER,
        detail TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE journals (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL,
        body TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
]


@dataclass(frozen=True)
class User:
    id: int
    public_id: str
    email: str
    password_hash: str | None
    role: Role
    status: Status
    display_name: str
    job_title: str
    establishment: str
    default_unit: str
    analytics_consent: bool | None
    created_at: str
    last_login_at: str | None

    def public(self) -> dict[str, Any]:
        """What the account owner (and an administrator) may see; never the password hash."""
        return {
            "id": self.public_id,
            "email": self.email,
            "role": self.role,
            "status": self.status,
            "display_name": self.display_name,
            "job_title": self.job_title,
            "establishment": self.establishment,
            "default_unit": self.default_unit,
            "analytics_consent": self.analytics_consent,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


class RevisionConflict(Exception):
    """The journal changed since the revision the client read (another tab or device)."""


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds")


def _user(row: sqlite3.Row) -> User:
    consent = row["analytics_consent"]
    return User(
        id=row["id"],
        public_id=row["public_id"],
        email=row["email"],
        password_hash=row["password_hash"],
        role=row["role"],
        status=row["status"],
        display_name=row["display_name"],
        job_title=row["job_title"],
        establishment=row["establishment"],
        default_unit=row["default_unit"],
        analytics_consent=None if consent is None else bool(consent),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


def normalise_email(email: str) -> str:
    return email.strip().lower()


class Store:
    def __init__(self, path: Path | str, clock: Clock = lambda: datetime.now(UTC)) -> None:
        self.clock = clock
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.RLock()
        self.migrate()

    # ------------------------------------------------------------------ infrastructure
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def migrate(self) -> int:
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL, applied_at "
                "TEXT NOT NULL)"
            )
            row = self._db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for version, script in enumerate(MIGRATIONS, start=1):
                if version <= current:
                    continue
                self._db.executescript(
                    f"BEGIN; {script} INSERT INTO schema_version VALUES ({version}, "
                    f"'{_iso(self.clock())}'); COMMIT;"
                )
            return len(MIGRATIONS)

    def backup(self, target: Path) -> None:
        """Consistent online copy (SQLite backup API), usable while the service runs."""
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(str(target)) as dst:
            self._db.backup(dst)

    def now(self) -> str:
        return _iso(self.clock())

    # ------------------------------------------------------------------ users
    def user_by_email(self, email: str) -> User | None:
        row = self._db.execute(
            "SELECT * FROM users WHERE email = ?", (normalise_email(email),)
        ).fetchone()
        return _user(row) if row else None

    def user_by_id(self, user_id: int) -> User | None:
        row = self._db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user(row) if row else None

    def user_by_public_id(self, public_id: str) -> User | None:
        row = self._db.execute("SELECT * FROM users WHERE public_id = ?", (public_id,)).fetchone()
        return _user(row) if row else None

    def users(self) -> list[User]:
        return [_user(r) for r in self._db.execute("SELECT * FROM users ORDER BY created_at, id")]

    def admin_count(self) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()
        return int(row["n"])

    def create_invited(
        self, email: str, role: Role, display_name: str, actor_id: int | None
    ) -> User:
        now = self.now()
        with self.tx() as db:
            cur = db.execute(
                "INSERT INTO users (public_id, email, role, status, display_name, created_at, "
                "updated_at) "
                "VALUES (?, ?, ?, 'invited', ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    normalise_email(email),
                    role,
                    display_name.strip()[:80],
                    now,
                    now,
                ),
            )
            user_id = int(cur.lastrowid or 0)
            self._audit(db, actor_id, "user.invited", user_id, {"role": role})
        user = self.user_by_id(user_id)
        assert user is not None
        return user

    def activate(self, user_id: int, password_hash: str) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE users SET password_hash = ?, status = 'active', updated_at = ? WHERE id "
                "= ? AND status != 'disabled'",
                (password_hash, self.now(), user_id),
            )
            self._audit(db, user_id, "user.activated", user_id, {})

    def set_password(
        self, user_id: int, password_hash: str, actor_id: int | None, reason: str
    ) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (password_hash, self.now(), user_id),
            )
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            self._audit(db, actor_id, "user.password_changed", user_id, {"reason": reason})

    def update_profile(self, user_id: int, fields: dict[str, Any]) -> User:
        allowed = {
            "display_name",
            "job_title",
            "establishment",
            "default_unit",
            "analytics_consent",
        }
        changes = {k: v for k, v in fields.items() if k in allowed}
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes)
            values = [
                int(v) if k == "analytics_consent" and v is not None else v
                for k, v in changes.items()
            ]
            with self.tx() as db:
                db.execute(
                    f"UPDATE users SET {sets}, updated_at = ? WHERE id = ?",
                    (*values, self.now(), user_id),
                )  # noqa: S608 (fixed column names)
                self._audit(
                    db, user_id, "user.profile_updated", user_id, {"fields": sorted(changes)}
                )
        user = self.user_by_id(user_id)
        assert user is not None
        return user

    def set_role_status(
        self, user_id: int, actor_id: int, role: Role | None, status: Status | None
    ) -> User:
        with self.tx() as db:
            if role is not None:
                db.execute(
                    "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                    (role, self.now(), user_id),
                )
            if status is not None:
                db.execute(
                    "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
                    (status, self.now(), user_id),
                )
                if status == "disabled":
                    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                    db.execute(
                        "UPDATE one_time_tokens SET used_at = ? WHERE user_id = ? AND used_at IS "
                        "NULL",
                        (self.now(), user_id),
                    )
            self._audit(db, actor_id, "user.updated", user_id, {"role": role, "status": status})
        user = self.user_by_id(user_id)
        assert user is not None
        return user

    # ------------------------------------------------------------------ sessions
    def create_session(self, user_id: int, absolute_hours: int, user_agent: str) -> str:
        token = security.new_token()
        now = self.clock()
        with self.tx() as db:
            db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    security.token_hash(token),
                    user_id,
                    _iso(now),
                    _iso(now),
                    _iso(now + timedelta(hours=absolute_hours)),
                    user_agent[:200],
                ),
            )
            db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_iso(now), user_id))
            self._audit(db, user_id, "session.created", user_id, {})
        return token

    def session_user(self, token: str, idle_minutes: int) -> User | None:
        """User of a valid session (active account, within absolute and idle limits); refreshes
        last_seen.
        """
        h = security.token_hash(token)
        row = self._db.execute("SELECT * FROM sessions WHERE token_hash = ?", (h,)).fetchone()
        if row is None:
            return None
        now = self.clock()
        expired = datetime.fromisoformat(row["expires_at"]) <= now
        idle = datetime.fromisoformat(row["last_seen_at"]) + timedelta(minutes=idle_minutes) <= now
        user = self.user_by_id(row["user_id"])
        if expired or idle or user is None or user.status != "active":
            with self.tx() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (h,))
            return None
        with self.tx() as db:
            db.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (_iso(now), h))
        return user

    def delete_session(self, token: str) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (security.token_hash(token),))

    def delete_sessions_except(self, user_id: int, keep_token: str | None) -> None:
        keep = security.token_hash(keep_token) if keep_token else ""
        with self.tx() as db:
            db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep)
            )

    # ------------------------------------------------------------------ one-time tokens
    def create_token(self, user_id: int, kind: TokenKind, valid_for: timedelta) -> str:
        token = security.new_token()
        now = self.clock()
        with self.tx() as db:
            # A new link replaces the previous ones of the same kind.
            db.execute(
                "UPDATE one_time_tokens SET used_at = ? WHERE user_id = ? AND kind = ? AND "
                "used_at IS NULL",
                (_iso(now), user_id, kind),
            )
            db.execute(
                "INSERT INTO one_time_tokens VALUES (?, ?, ?, ?, ?, NULL)",
                (security.token_hash(token), user_id, kind, _iso(now), _iso(now + valid_for)),
            )
        return token

    def peek_token(self, token: str, kind: TokenKind) -> User | None:
        row = self._db.execute(
            "SELECT * FROM one_time_tokens WHERE token_hash = ? AND kind = ?",
            (security.token_hash(token), kind),
        ).fetchone()
        if (
            row is None
            or row["used_at"] is not None
            or datetime.fromisoformat(row["expires_at"]) <= self.clock()
        ):
            return None
        user = self.user_by_id(row["user_id"])
        return user if user is not None and user.status != "disabled" else None

    def consume_token(self, token: str, kind: TokenKind) -> User | None:
        user = self.peek_token(token, kind)
        if user is None:
            return None
        with self.tx() as db:
            cur = db.execute(
                "UPDATE one_time_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                (self.now(), security.token_hash(token)),
            )
            if cur.rowcount != 1:
                return None
        return user

    # ------------------------------------------------------------------ login throttling
    def record_failure(self, email: str, ip: str) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO login_failures (email, ip, at) VALUES (?, ?, ?)",
                (normalise_email(email), ip, self.now()),
            )
            db.execute(
                "DELETE FROM login_failures WHERE at < ?", (_iso(self.clock() - timedelta(days=1)),)
            )

    def failures(self, email: str, ip: str, window: timedelta) -> tuple[int, int]:
        since = _iso(self.clock() - window)
        by_email = self._db.execute(
            "SELECT COUNT(*) AS n FROM login_failures WHERE email = ? AND at >= ?",
            (normalise_email(email), since),
        ).fetchone()["n"]
        by_ip = self._db.execute(
            "SELECT COUNT(*) AS n FROM login_failures WHERE ip = ? AND at >= ?", (ip, since)
        ).fetchone()["n"]
        return int(by_email), int(by_ip)

    def clear_failures(self, email: str) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM login_failures WHERE email = ?", (normalise_email(email),))

    # ------------------------------------------------------------------ audit
    def _audit(
        self,
        db: sqlite3.Connection,
        actor_id: int | None,
        action: str,
        target_id: int | None,
        detail: dict[str, Any],
    ) -> None:
        db.execute(
            "INSERT INTO audit (at, actor_id, action, target_id, detail) VALUES (?, ?, ?, ?, ?)",
            (self.now(), actor_id, action, target_id, json.dumps(detail, sort_keys=True)),
        )

    def audit(
        self,
        actor_id: int | None,
        action: str,
        target_id: int | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self.tx() as db:
            self._audit(db, actor_id, action, target_id, detail or {})

    def audit_trail(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) | {"detail": json.loads(r["detail"])} for r in rows]

    # ------------------------------------------------------------------ journals (one document per
    # account)
    def journal(self, user_id: int) -> tuple[int, list[Any]]:
        row = self._db.execute(
            "SELECT revision, body FROM journals WHERE user_id = ?", (user_id,)
        ).fetchone()
        return (0, []) if row is None else (int(row["revision"]), json.loads(row["body"]))

    def save_journal(self, user_id: int, base_revision: int, records: list[Any]) -> int:
        body = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
        with self.tx() as db:
            row = db.execute(
                "SELECT revision FROM journals WHERE user_id = ?", (user_id,)
            ).fetchone()
            current = 0 if row is None else int(row["revision"])
            if current != base_revision:
                raise RevisionConflict(f"journal revision is {current}, not {base_revision}")
            db.execute(
                "INSERT INTO journals VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                "revision = excluded.revision, body = excluded.body, updated_at = "
                "excluded.updated_at",
                (user_id, current + 1, body, self.now()),
            )
        return current + 1
