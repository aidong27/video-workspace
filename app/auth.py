"""People, roles and browser sessions.

Everyone gets in with an activation code (see ``access.py``). This module owns
the auth database schema, the session cookie and the role checks. A session
stores only a SHA-256 of its token and remembers the activation code that
opened it: when that code is revoked, expires, or its person is disabled, the
session stops resolving on the very next request.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any, Iterator

from fastapi import HTTPException, Request, Response

from .database import sqlite_connection

SESSION_COOKIE_BASE = "caption_session"
ROLES = ("owner", "member")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    created_at INTEGER NOT NULL,
    last_login_at INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash BLOB NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE TABLE IF NOT EXISTS access_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash BLOB NOT NULL UNIQUE,
    hint TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    revoked_at INTEGER,
    last_used_at INTEGER,
    use_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_access_codes_user_id ON access_codes(user_id);
CREATE TABLE IF NOT EXISTS gate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at INTEGER NOT NULL,
    kind TEXT NOT NULL,
    ip TEXT NOT NULL,
    user_id INTEGER,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_gate_events_ip_at ON gate_events(ip, at);
CREATE INDEX IF NOT EXISTS idx_gate_events_at ON gate_events(at);
CREATE TABLE IF NOT EXISTS usage_daily (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    jobs INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
"""

# Columns added after the first release; applied in order, idempotently.
COLUMN_MIGRATIONS = (
    ("users", "role", "TEXT NOT NULL DEFAULT 'member'"),
    ("users", "display_name", "TEXT"),
    ("users", "max_devices", "INTEGER"),
    ("users", "daily_job_limit", "INTEGER"),
    ("sessions", "code_id", "INTEGER"),
    ("sessions", "user_agent", "TEXT"),
    ("sessions", "ip", "TEXT"),
)


@dataclass(frozen=True)
class AuthUser:
    user_id: int
    username: str
    created_at: int
    role: str = "member"
    display_name: str = ""

    @property
    def label(self) -> str:
        return self.display_name or self.username


class AuthFailure(Exception):
    def __init__(self, status_code: int, message: str, reason: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.reason = reason
        self.extra = extra


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return max(minimum, default)


def auth_db_path() -> Path:
    return Path(os.getenv("AUTH_DB_PATH", "/opt/bili-subtitle-tool/var/auth/auth.db"))


def session_ttl_seconds() -> int:
    return _env_int("AUTH_SESSION_TTL_DAYS", 30, 1) * 24 * 60 * 60


def device_limit(role: str, override: int | None) -> int:
    """How many signed-in browsers one person may keep at once."""
    if override:
        return max(1, int(override))
    if role == "owner":
        return _env_int("ACCESS_OWNER_MAX_DEVICES", 10, 1)
    return _env_int("ACCESS_MAX_DEVICES", 3, 1)


def admin_usernames() -> frozenset[str]:
    return frozenset(
        username.strip().casefold()
        for username in os.getenv("ADMIN_USERNAMES", "").split(",")
        if username.strip()
    )


def cookie_secure() -> bool:
    return _env_bool("AUTH_COOKIE_SECURE", True)


def session_cookie_name() -> str:
    # The __Host- prefix forbids a Domain attribute, so a sibling subdomain of
    # a shared parent domain cannot plant or overwrite the session cookie.
    return f"__Host-{SESSION_COOKIE_BASE}" if cookie_secure() else SESSION_COOKIE_BASE


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite_connection(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


def _apply_column_migrations(connection: sqlite3.Connection) -> None:
    for table, column, definition in COLUMN_MIGRATIONS:
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize_auth_db() -> None:
    path = auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    now = int(time.time())
    with connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
        _apply_column_migrations(connection)
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        # Password sessions from before activation codes no longer grant access.
        connection.execute("DELETE FROM sessions WHERE code_id IS NULL")
        connection.execute("DELETE FROM gate_events WHERE at <= ?", (now - 30 * 86_400,))
        connection.execute(
            "DELETE FROM usage_daily WHERE day < ?",
            (time.strftime("%Y-%m-%d", time.gmtime(now - 40 * 86_400)),),
        )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def insert_session(
    connection: sqlite3.Connection,
    user_id: int,
    *,
    code_id: int,
    limit: int,
    user_agent: str | None = None,
    ip: str | None = None,
    now: int | None = None,
) -> tuple[str, int]:
    """Create a session inside the caller's transaction, evicting the oldest
    sessions of that person beyond their device limit."""
    current = int(time.time()) if now is None else int(now)
    token = secrets.token_urlsafe(32)
    expires_at = current + session_ttl_seconds()
    connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (current,))
    rows = connection.execute(
        "SELECT id FROM sessions WHERE user_id = ? ORDER BY last_seen_at DESC, id DESC",
        (user_id,),
    ).fetchall()
    for row in rows[max(0, limit - 1):]:
        connection.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
    connection.execute(
        "INSERT INTO sessions(user_id, token_hash, created_at, expires_at, last_seen_at, code_id, user_agent, ip) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            sqlite3.Binary(_token_hash(token)),
            current,
            expires_at,
            current,
            code_id,
            (user_agent or "")[:240] or None,
            (ip or "")[:64] or None,
        ),
    )
    return token, expires_at


def resolve_session(token: str | None) -> AuthUser | None:
    if not token or len(token) > 128:
        return None
    now = int(time.time())
    with connect() as connection:
        row = connection.execute(
            "SELECT users.id, users.username, users.created_at, users.is_active, users.role, "
            "users.display_name, sessions.id AS session_id, sessions.expires_at, sessions.last_seen_at, "
            "access_codes.id AS code_row, access_codes.revoked_at, access_codes.expires_at AS code_expires_at "
            "FROM sessions JOIN users ON users.id = sessions.user_id "
            "LEFT JOIN access_codes ON access_codes.id = sessions.code_id "
            "WHERE sessions.token_hash = ?",
            (sqlite3.Binary(_token_hash(token)),),
        ).fetchone()
        if row is None:
            return None
        code_valid = (
            row["code_row"] is not None
            and row["revoked_at"] is None
            and (row["code_expires_at"] is None or int(row["code_expires_at"]) > now)
        )
        if not row["is_active"] or int(row["expires_at"]) <= now or not code_valid:
            connection.execute("DELETE FROM sessions WHERE id = ?", (row["session_id"],))
            return None
        if now - int(row["last_seen_at"]) >= 600:
            connection.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, row["session_id"]))
    return AuthUser(
        user_id=int(row["id"]),
        username=str(row["username"]),
        created_at=int(row["created_at"]),
        role=str(row["role"] or "member"),
        display_name=str(row["display_name"] or ""),
    )


def delete_session(token: str | None) -> None:
    if not token:
        return
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (sqlite3.Binary(_token_hash(token)),))


def delete_user_sessions(user_id: int) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def account_summary(user_id: int) -> dict[str, Any]:
    now = int(time.time())
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        row = connection.execute(
            "SELECT users.created_at, users.last_login_at, users.max_devices, users.role, "
            "access_codes.hint, access_codes.expires_at AS code_expires_at "
            "FROM users LEFT JOIN access_codes "
            "ON access_codes.user_id = users.id AND access_codes.revoked_at IS NULL "
            "WHERE users.id = ? AND users.is_active = 1 ORDER BY access_codes.id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row is None:
            raise AuthFailure(401, "当前账号不可用，请重新验证。", "authentication_required")
        active_sessions = int(
            connection.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)).fetchone()[0]
        )
    return {
        "created_at": int(row["created_at"]),
        "last_login_at": int(row["last_login_at"]) if row["last_login_at"] is not None else None,
        "active_sessions": active_sessions,
        "max_devices": device_limit(str(row["role"] or "member"), row["max_devices"]),
        "code_hint": row["hint"],
        "code_expires_at": int(row["code_expires_at"]) if row["code_expires_at"] is not None else None,
    }


def user_count() -> int:
    with connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0])


def auth_user_from_request(request: Request) -> AuthUser | None:
    cached: Any = getattr(request.state, "auth_user", None)
    if isinstance(cached, AuthUser):
        return cached
    return resolve_session(request.cookies.get(session_cookie_name()))


def require_auth_user(request: Request) -> AuthUser:
    user = auth_user_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"reason": "authentication_required", "message": "请先输入激活码。"},
        )
    return user


def is_admin_user(user: AuthUser | None) -> bool:
    if user is None:
        return False
    return user.role == "owner" or user.username.casefold() in admin_usernames()


def require_admin_user(request: Request) -> AuthUser:
    user = require_auth_user(request)
    if not is_admin_user(user):
        raise HTTPException(
            status_code=403,
            detail={"reason": "admin_required", "message": "需要站长权限。"},
        )
    return user


def set_session_cookie(response: Response, token: str, expires_at: int) -> None:
    max_age = max(1, expires_at - int(time.time()))
    response.set_cookie(
        key=session_cookie_name(),
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=session_cookie_name(),
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def auth_error(exc: AuthFailure) -> HTTPException:
    headers = None
    retry_after = exc.extra.get("retry_after")
    if isinstance(retry_after, int) and retry_after > 0:
        headers = {"Retry-After": str(retry_after)}
    return HTTPException(
        status_code=exc.status_code,
        detail={"reason": exc.reason, "message": exc.message, **exc.extra},
        headers=headers,
    )
