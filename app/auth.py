from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any

from fastapi import HTTPException, Request, Response


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
SESSION_COOKIE_NAME = "caption_session"
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


@dataclass(frozen=True)
class AuthUser:
    user_id: int
    username: str
    created_at: int


class AuthFailure(Exception):
    def __init__(self, status_code: int, message: str, reason: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.reason = reason


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
    days = _env_int("AUTH_SESSION_TTL_DAYS", 30, 1)
    return days * 24 * 60 * 60


def max_sessions_per_user() -> int:
    return _env_int("AUTH_MAX_SESSIONS_PER_USER", 8, 1)


def invite_configured() -> bool:
    value = os.getenv("INVITE_CODE_HASH", "").strip().lower()
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _connect() -> sqlite3.Connection:
    path = auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize_auth_db() -> None:
    path = auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    with _connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
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
            """
        )
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _normalize_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.fullmatch(value):
        raise AuthFailure(400, "用户名需为 3-32 位字母、数字、点、下划线或连字符。", "invalid_username")
    return value


def _validate_password(password: str) -> str:
    value = password or ""
    if len(value) < PASSWORD_MIN_LENGTH:
        raise AuthFailure(400, f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符。", "password_too_short")
    if len(value) > PASSWORD_MAX_LENGTH:
        raise AuthFailure(400, f"密码不能超过 {PASSWORD_MAX_LENGTH} 个字符。", "password_too_long")
    return value


def _password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=64 * 1024 * 1024,
    )


def _verify_invite_code(invite_code: str) -> None:
    expected = os.getenv("INVITE_CODE_HASH", "").strip().lower()
    if not invite_configured():
        raise AuthFailure(503, "注册邀请码尚未配置。", "registration_unavailable")
    actual = hashlib.sha256((invite_code or "").strip().encode("utf-8")).hexdigest()
    if not secrets.compare_digest(actual, expected):
        raise AuthFailure(403, "邀请码不正确。", "invalid_invite_code")


def register_user(username: str, password: str, invite_code: str) -> AuthUser:
    normalized_username = _normalize_username(username)
    validated_password = _validate_password(password)
    _verify_invite_code(invite_code)
    salt = secrets.token_bytes(16)
    digest = _password_digest(validated_password, salt)
    now = int(time.time())
    max_users = _env_int("AUTH_MAX_USERS", 50, 1)
    try:
        with _connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            if count >= max_users:
                raise AuthFailure(403, "账号数量已达到服务器上限。", "user_limit_reached")
            cursor = connection.execute(
                "INSERT INTO users(username, password_salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (normalized_username, sqlite3.Binary(salt), sqlite3.Binary(digest), now),
            )
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise AuthFailure(409, "这个用户名已经被注册。", "username_taken") from exc
    return AuthUser(user_id=user_id, username=normalized_username, created_at=now)


def authenticate_user(username: str, password: str) -> AuthUser:
    value = (username or "").strip()
    supplied_password = password or ""
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, username, password_salt, password_hash, created_at, is_active "
            "FROM users WHERE username = ? COLLATE NOCASE",
            (value,),
        ).fetchone()
        if row is None or not row["is_active"]:
            _password_digest(supplied_password, b"\x00" * 16)
            raise AuthFailure(401, "用户名或密码不正确。", "invalid_credentials")
        try:
            digest = _password_digest(supplied_password, bytes(row["password_salt"]))
        except (ValueError, TypeError):
            raise AuthFailure(401, "用户名或密码不正确。", "invalid_credentials") from None
        if not secrets.compare_digest(digest, bytes(row["password_hash"])):
            raise AuthFailure(401, "用户名或密码不正确。", "invalid_credentials")
        connection.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (int(time.time()), row["id"]))
    return AuthUser(user_id=int(row["id"]), username=str(row["username"]), created_at=int(row["created_at"]))


def create_session(user: AuthUser) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).digest()
    now = int(time.time())
    expires_at = now + session_ttl_seconds()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        max_sessions = max_sessions_per_user()
        rows = connection.execute(
            "SELECT id FROM sessions WHERE user_id = ? ORDER BY last_seen_at DESC, id DESC",
            (user.user_id,),
        ).fetchall()
        for row in rows[max_sessions - 1 :]:
            connection.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
        connection.execute(
            "INSERT INTO sessions(user_id, token_hash, created_at, expires_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.user_id, sqlite3.Binary(token_hash), now, expires_at, now),
        )
    return token, expires_at


def resolve_session(token: str | None) -> AuthUser | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).digest()
    now = int(time.time())
    with _connect() as connection:
        row = connection.execute(
            "SELECT users.id, users.username, users.created_at, users.is_active, "
            "sessions.id AS session_id, sessions.expires_at, sessions.last_seen_at "
            "FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.token_hash = ?",
            (sqlite3.Binary(token_hash),),
        ).fetchone()
        if row is None:
            return None
        if not row["is_active"] or int(row["expires_at"]) <= now:
            connection.execute("DELETE FROM sessions WHERE id = ?", (row["session_id"],))
            return None
        if now - int(row["last_seen_at"]) >= 3600:
            connection.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, row["session_id"]))
    return AuthUser(user_id=int(row["id"]), username=str(row["username"]), created_at=int(row["created_at"]))


def delete_session(token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).digest()
    with _connect() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (sqlite3.Binary(token_hash),))


def delete_user_sessions(user_id: int) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def change_password(user_id: int, current_password: str, new_password: str) -> AuthUser:
    validated_password = _validate_password(new_password)
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id, username, password_salt, password_hash, created_at, is_active "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None or not row["is_active"]:
            raise AuthFailure(401, "当前账号不可用，请重新登录。", "authentication_required")
        try:
            current_digest = _password_digest(current_password or "", bytes(row["password_salt"]))
        except (ValueError, TypeError):
            raise AuthFailure(400, "当前密码不正确。", "current_password_invalid") from None
        if not secrets.compare_digest(current_digest, bytes(row["password_hash"])):
            raise AuthFailure(400, "当前密码不正确。", "current_password_invalid")
        if secrets.compare_digest(
            _password_digest(validated_password, bytes(row["password_salt"])),
            bytes(row["password_hash"]),
        ):
            raise AuthFailure(400, "新密码不能与当前密码相同。", "password_unchanged")
        salt = secrets.token_bytes(16)
        digest = _password_digest(validated_password, salt)
        connection.execute(
            "UPDATE users SET password_salt = ?, password_hash = ? WHERE id = ?",
            (sqlite3.Binary(salt), sqlite3.Binary(digest), user_id),
        )
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return AuthUser(
        user_id=int(row["id"]),
        username=str(row["username"]),
        created_at=int(row["created_at"]),
    )


def account_summary(user_id: int) -> dict[str, int | None]:
    now = int(time.time())
    with _connect() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        row = connection.execute(
            "SELECT created_at, last_login_at FROM users WHERE id = ? AND is_active = 1",
            (user_id,),
        ).fetchone()
        if row is None:
            raise AuthFailure(401, "当前账号不可用，请重新登录。", "authentication_required")
        active_sessions = int(
            connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        )
    return {
        "created_at": int(row["created_at"]),
        "last_login_at": int(row["last_login_at"]) if row["last_login_at"] is not None else None,
        "active_sessions": active_sessions,
    }


def user_count() -> int:
    with _connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0])


def auth_user_from_request(request: Request) -> AuthUser | None:
    cached: Any = getattr(request.state, "auth_user", None)
    if isinstance(cached, AuthUser):
        return cached
    return resolve_session(request.cookies.get(SESSION_COOKIE_NAME))


def require_auth_user(request: Request) -> AuthUser:
    user = auth_user_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"reason": "authentication_required", "message": "请先登录。"},
        )
    return user


def set_session_cookie(response: Response, token: str, expires_at: int) -> None:
    max_age = max(1, expires_at - int(time.time()))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        secure=_env_bool("AUTH_COOKIE_SECURE", True),
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=_env_bool("AUTH_COOKIE_SECURE", True),
        httponly=True,
        samesite="lax",
    )


def auth_error(exc: AuthFailure) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"reason": exc.reason, "message": exc.message},
    )
