"""Activation codes: the only way into the site.

The owner hands each person one code. A code is 20 Crockford base32
characters (100 random bits), shown exactly once and stored only as an HMAC
under a server-side pepper, so a copied database does not reveal any code.
Every person is a user row: resetting someone's code keeps their history and
quota while the old code, and every session it opened, stops working.

The gate keeps an event log in the auth database. Failed attempts are counted
per client address; repeated failures lock that address out for 15 minutes,
then an hour, then a day. A successful entry forgives the address.

Command line (run as the service user, with AUTH_DB_PATH set):

    python -m app.access issue --label 站长 --owner --username aidong27
    python -m app.access issue --label 小王 --days 90
    python -m app.access list
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
from threading import Lock
import time
from typing import Any

from .auth import (
    ROLES,
    AuthFailure,
    AuthUser,
    auth_db_path,
    connect,
    device_limit,
    initialize_auth_db,
    insert_session,
)

CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 20
CODE_GROUP = 5
_CONFUSABLE = str.maketrans({"O": "0", "I": "1", "L": "1"})
_SEPARATORS = re.compile(r"[\s\-_.·—–]+")
CHINA = timezone(timedelta(hours=8))
LABEL_MAX_LENGTH = 24

# (failures, counted within seconds, locked for seconds) — strictest first.
LOCK_RULES = (
    (20, 86_400, 86_400),
    (10, 86_400, 3_600),
    (5, 900, 900),
)
EVENT_RETENTION_SECONDS = 30 * 86_400

_PEPPER_LOCK = Lock()
_PEPPER_CACHE: dict[Path, bytes] = {}


@dataclass(frozen=True)
class Activation:
    user: AuthUser
    token: str
    expires_at: int


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def pepper() -> bytes:
    configured = os.getenv("ACCESS_CODE_PEPPER", "").strip()
    if len(configured) >= 32:
        return configured.encode("utf-8")
    path = auth_db_path().parent / "access-pepper"
    with _PEPPER_LOCK:
        cached = _PEPPER_CACHE.get(path)
        if cached:
            return cached
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            value = path.read_bytes()
        except FileNotFoundError:
            value = secrets.token_bytes(32)
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                value = path.read_bytes()
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(value)
                    handle.flush()
                    os.fsync(handle.fileno())
        if len(value) < 32:
            raise RuntimeError("access code pepper is too short")
        _PEPPER_CACHE[path] = value
        return value


def generate_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[index:index + CODE_GROUP] for index in range(0, CODE_LENGTH, CODE_GROUP))


def normalize_code(value: str | None) -> str | None:
    cleaned = _SEPARATORS.sub("", value or "").upper().translate(_CONFUSABLE)
    if len(cleaned) != CODE_LENGTH or any(char not in CODE_ALPHABET for char in cleaned):
        return None
    return cleaned


def code_digest(normalized: str) -> bytes:
    return hmac.new(pepper(), b"activation-code:v1:" + normalized.encode("ascii"), hashlib.sha256).digest()


def china_day(now: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, CHINA).strftime("%Y-%m-%d")


def seconds_until_reset(now: float | None = None) -> int:
    current = datetime.fromtimestamp(time.time() if now is None else now, CHINA)
    tomorrow = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - current).total_seconds()))


def format_wait(seconds: int) -> str:
    if seconds >= 3600:
        return f"{max(1, round(seconds / 3600))} 小时"
    if seconds >= 60:
        return f"{max(1, round(seconds / 60))} 分钟"
    return f"{max(1, seconds)} 秒"


def clean_label(value: str | None) -> str:
    label = re.sub(r"[\x00-\x1f\x7f<>]", "", (value or "").strip())[:LABEL_MAX_LENGTH].strip()
    if not label:
        raise AuthFailure(400, "请填写这个激活码给谁用。", "label_required")
    return label


# ---------------------------------------------------------------- the gate


def _record(connection: sqlite3.Connection, kind: str, ip: str, now: int, *,
            user_id: int | None = None, detail: str | None = None) -> None:
    connection.execute(
        "INSERT INTO gate_events(at, kind, ip, user_id, detail) VALUES (?, ?, ?, ?, ?)",
        (now, kind, ip, user_id, detail),
    )


def _lock_remaining(connection: sqlite3.Connection, ip: str, now: int) -> int:
    for failures, window, duration in LOCK_RULES:
        count, last = connection.execute(
            "SELECT COUNT(*), MAX(at) FROM gate_events WHERE ip = ? AND kind = 'denied' AND at > ?",
            (ip, now - window),
        ).fetchone()
        if count >= failures and last is not None and int(last) + duration > now:
            return int(last) + duration - now
    return 0


def _attempts_left(connection: sqlite3.Connection, ip: str, now: int) -> int:
    failures, window, _ = LOCK_RULES[-1]
    count = connection.execute(
        "SELECT COUNT(*) FROM gate_events WHERE ip = ? AND kind = 'denied' AND at > ?",
        (ip, now - window),
    ).fetchone()[0]
    return max(0, failures - int(count))


def gate_locked_failure(retry_after: int) -> AuthFailure:
    return AuthFailure(
        429,
        f"尝试次数过多，这个网络已被暂时锁定，请 {format_wait(retry_after)}后再试。",
        "gate_locked",
        retry_after=retry_after,
    )


def activate(code_input: str, ip: str | None, user_agent: str | None = None) -> Activation:
    """Exchange an activation code for a session, or record a failed attempt."""
    address = (ip or "unknown")[:64]
    now = int(time.time())
    normalized = normalize_code(code_input)
    digest = code_digest(normalized) if normalized else None
    failure: AuthFailure | None = None
    result: Activation | None = None
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM gate_events WHERE at <= ?", (now - EVENT_RETENTION_SECONDS,))
        locked = _lock_remaining(connection, address, now)
        if locked:
            failure = gate_locked_failure(locked)
        else:
            row = None
            if digest is not None:
                row = connection.execute(
                    "SELECT access_codes.id AS code_id, access_codes.expires_at, access_codes.revoked_at, "
                    "users.id, users.username, users.created_at, users.is_active, users.role, "
                    "users.display_name, users.max_devices "
                    "FROM access_codes JOIN users ON users.id = access_codes.user_id "
                    "WHERE access_codes.code_hash = ?",
                    (sqlite3.Binary(digest),),
                ).fetchone()
            reason = None
            if row is None:
                reason = "unknown" if normalized else "malformed"
            elif row["revoked_at"] is not None or not row["is_active"]:
                reason = "revoked"
            elif row["expires_at"] is not None and int(row["expires_at"]) <= now:
                reason = "expired"
            if reason is not None:
                _record(connection, "denied", address, now, user_id=row["id"] if row else None, detail=reason)
                locked = _lock_remaining(connection, address, now)
                if locked:
                    failure = gate_locked_failure(locked)
                elif reason == "revoked":
                    failure = AuthFailure(403, "这个激活码已停用，请联系站长。", "code_revoked")
                elif reason == "expired":
                    failure = AuthFailure(403, "这个激活码已过期，请联系站长续期。", "code_expired")
                else:
                    failure = AuthFailure(
                        401,
                        "激活码不正确。",
                        "invalid_code",
                        attempts_left=_attempts_left(connection, address, now),
                    )
            else:
                user_id = int(row["id"])
                connection.execute(
                    "UPDATE access_codes SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
                    (now, row["code_id"]),
                )
                connection.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))
                connection.execute(
                    "UPDATE gate_events SET kind = 'forgiven' WHERE ip = ? AND kind = 'denied'",
                    (address,),
                )
                _record(connection, "granted", address, now, user_id=user_id)
                role = str(row["role"] or "member")
                token, expires_at = insert_session(
                    connection,
                    user_id,
                    code_id=int(row["code_id"]),
                    limit=device_limit(role, row["max_devices"]),
                    user_agent=user_agent,
                    ip=address,
                    now=now,
                )
                result = Activation(
                    user=AuthUser(
                        user_id=user_id,
                        username=str(row["username"]),
                        created_at=int(row["created_at"]),
                        role=role,
                        display_name=str(row["display_name"] or ""),
                    ),
                    token=token,
                    expires_at=expires_at,
                )
    if failure is not None:
        raise failure
    assert result is not None
    return result


# ------------------------------------------------------------ daily quota


def daily_job_limit(role: str, override: int | None) -> int | None:
    """None means unlimited. The owner is never limited."""
    if role == "owner":
        return None
    if override is not None:
        return int(override) if int(override) > 0 else None
    configured = _env_int("MEMBER_DAILY_JOB_LIMIT", 30)
    return configured if configured > 0 else None


def quota_status(user_id: int, now: float | None = None) -> dict[str, Any]:
    day = china_day(now)
    with connect() as connection:
        row = connection.execute(
            "SELECT users.role, users.daily_job_limit, usage_daily.jobs FROM users "
            "LEFT JOIN usage_daily ON usage_daily.user_id = users.id AND usage_daily.day = ? "
            "WHERE users.id = ?",
            (day, user_id),
        ).fetchone()
    if row is None:
        return {"used": 0, "limit": None, "remaining": None, "resets_in": seconds_until_reset(now)}
    used = int(row["jobs"] or 0)
    limit = daily_job_limit(str(row["role"] or "member"), row["daily_job_limit"])
    return {
        "used": used,
        "limit": limit,
        "remaining": None if limit is None else max(0, limit - used),
        "resets_in": seconds_until_reset(now),
    }


def consume_job_quota(user_id: int, now: float | None = None) -> None:
    day = china_day(now)
    failure: AuthFailure | None = None
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT users.role, users.daily_job_limit, usage_daily.jobs FROM users "
            "LEFT JOIN usage_daily ON usage_daily.user_id = users.id AND usage_daily.day = ? "
            "WHERE users.id = ?",
            (day, user_id),
        ).fetchone()
        if row is None:
            failure = AuthFailure(401, "当前账号不可用，请重新验证。", "authentication_required")
        else:
            used = int(row["jobs"] or 0)
            limit = daily_job_limit(str(row["role"] or "member"), row["daily_job_limit"])
            if limit is not None and used >= limit:
                failure = AuthFailure(
                    429,
                    f"今天的 {limit} 次任务额度已用完，零点后重置。",
                    "daily_quota_reached",
                    limit=limit,
                    used=used,
                    retry_after=seconds_until_reset(now),
                )
            else:
                connection.execute(
                    "INSERT INTO usage_daily(user_id, day, jobs) VALUES (?, ?, 1) "
                    "ON CONFLICT(user_id, day) DO UPDATE SET jobs = jobs + 1",
                    (user_id, day),
                )
    if failure is not None:
        raise failure


def refund_job_quota(user_id: int, now: float | None = None) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE usage_daily SET jobs = MAX(0, jobs - 1) WHERE user_id = ? AND day = ?",
            (user_id, china_day(now)),
        )


# ------------------------------------------------------------ owner tools


def _insert_code(connection: sqlite3.Connection, user_id: int, expires_at: int | None, now: int) -> str:
    for _ in range(5):
        code = generate_code()
        normalized = normalize_code(code)
        assert normalized is not None
        try:
            connection.execute(
                "INSERT INTO access_codes(user_id, code_hash, hint, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, sqlite3.Binary(code_digest(normalized)), normalized[-4:], now, expires_at),
            )
        except sqlite3.IntegrityError:
            continue
        return code
    raise RuntimeError("could not allocate a unique activation code")


def _expiry(expires_in_days: int | None, now: int) -> int | None:
    if not expires_in_days or int(expires_in_days) <= 0:
        return None
    return now + min(int(expires_in_days), 3650) * 86_400


def _check_limits(max_devices: int | None, daily_jobs: int | None) -> None:
    if max_devices is not None and not 1 <= int(max_devices) <= 20:
        raise AuthFailure(400, "设备数需在 1 到 20 之间。", "invalid_max_devices")
    if daily_jobs is not None and not 0 <= int(daily_jobs) <= 1000:
        raise AuthFailure(400, "每日任务数需在 0 到 1000 之间（0 表示不限）。", "invalid_daily_limit")


def issue_code(
    *,
    label: str,
    role: str = "member",
    max_devices: int | None = None,
    daily_job_limit: int | None = None,
    expires_in_days: int | None = None,
    user_id: int | None = None,
    username: str | None = None,
) -> tuple[str, int]:
    """Give a person a fresh code and return (code, user_id).

    ``user_id`` or ``username`` reuses an existing person; their previous
    codes are revoked and their sessions end. Otherwise a new person is made.
    """
    if role not in ROLES:
        raise AuthFailure(400, "未知角色。", "invalid_role")
    _check_limits(max_devices, daily_job_limit)
    name = clean_label(label)
    now = int(time.time())
    expires_at = _expiry(expires_in_days, now)
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = None
        if user_id is not None:
            row = connection.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise AuthFailure(404, "找不到这个成员。", "member_not_found")
        elif username:
            row = connection.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
        if row is None:
            handle = username or f"member-{secrets.token_hex(4)}"
            cursor = connection.execute(
                "INSERT INTO users(username, password_salt, password_hash, created_at, role, display_name, "
                "max_devices, daily_job_limit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    handle,
                    sqlite3.Binary(secrets.token_bytes(16)),
                    sqlite3.Binary(secrets.token_bytes(32)),
                    now,
                    role,
                    name,
                    max_devices,
                    daily_job_limit,
                ),
            )
            target = int(cursor.lastrowid)
        else:
            target = int(row["id"])
            connection.execute(
                "UPDATE access_codes SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, target),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (target,))
            connection.execute(
                "UPDATE users SET display_name = ?, is_active = 1, role = CASE WHEN ? = 'owner' THEN 'owner' "
                "ELSE role END WHERE id = ?",
                (name, role, target),
            )
            if max_devices is not None or daily_job_limit is not None:
                connection.execute(
                    "UPDATE users SET max_devices = COALESCE(?, max_devices), "
                    "daily_job_limit = COALESCE(?, daily_job_limit) WHERE id = ?",
                    (max_devices, daily_job_limit, target),
                )
        code = _insert_code(connection, target, expires_at, now)
    return code, target


def reset_code(user_id: int, expires_in_days: int | None = None) -> str:
    with connect() as connection:
        row = connection.execute(
            "SELECT users.display_name, users.username, access_codes.expires_at FROM users "
            "LEFT JOIN access_codes ON access_codes.user_id = users.id AND access_codes.revoked_at IS NULL "
            "WHERE users.id = ? ORDER BY access_codes.id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if row is None:
        raise AuthFailure(404, "找不到这个成员。", "member_not_found")
    if expires_in_days is None and row["expires_at"] is not None:
        expires_in_days = max(1, -(-(int(row["expires_at"]) - int(time.time())) // 86_400))
    code, _ = issue_code(
        label=row["display_name"] or row["username"],
        user_id=user_id,
        expires_in_days=expires_in_days,
    )
    return code


def _require_member(connection: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT id, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise AuthFailure(404, "找不到这个成员。", "member_not_found")
    return row


_UNSET: Any = object()


def update_member(
    user_id: int,
    *,
    label: Any = _UNSET,
    max_devices: Any = _UNSET,
    daily_job_limit: Any = _UNSET,
    active: Any = _UNSET,
    expires_in_days: Any = _UNSET,
) -> None:
    _check_limits(
        None if max_devices is _UNSET else max_devices,
        None if daily_job_limit is _UNSET else daily_job_limit,
    )
    now = int(time.time())
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _require_member(connection, user_id)
        if row["role"] == "owner" and active is not _UNSET and not active:
            raise AuthFailure(400, "不能停用站长自己。", "owner_protected")
        if label is not _UNSET:
            connection.execute("UPDATE users SET display_name = ? WHERE id = ?", (clean_label(label), user_id))
        if max_devices is not _UNSET:
            connection.execute("UPDATE users SET max_devices = ? WHERE id = ?", (max_devices, user_id))
            if max_devices:
                rows = connection.execute(
                    "SELECT id FROM sessions WHERE user_id = ? ORDER BY last_seen_at DESC, id DESC",
                    (user_id,),
                ).fetchall()
                for extra in rows[int(max_devices):]:
                    connection.execute("DELETE FROM sessions WHERE id = ?", (extra["id"],))
        if daily_job_limit is not _UNSET:
            connection.execute("UPDATE users SET daily_job_limit = ? WHERE id = ?", (daily_job_limit, user_id))
        if expires_in_days is not _UNSET:
            connection.execute(
                "UPDATE access_codes SET expires_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (_expiry(expires_in_days, now), user_id),
            )
        if active is not _UNSET:
            connection.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id))
            if not active:
                connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def sign_out_member(user_id: int) -> int:
    with connect() as connection:
        _require_member(connection, user_id)
        return connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)).rowcount


def end_session(user_id: int, session_id: int) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))


def delete_member(user_id: int) -> None:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _require_member(connection, user_id)
        if row["role"] == "owner":
            raise AuthFailure(400, "不能删除站长自己。", "owner_protected")
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))


def _code_state(row: sqlite3.Row, now: int) -> str:
    if not row["is_active"]:
        return "disabled"
    if row["code_id"] is None:
        return "no_code"
    if row["code_expires_at"] is not None and int(row["code_expires_at"]) <= now:
        return "expired"
    return "active"


def list_members() -> list[dict[str, Any]]:
    now = int(time.time())
    day = china_day(now)
    with connect() as connection:
        people = connection.execute(
            "SELECT users.id, users.username, users.display_name, users.role, users.is_active, users.created_at, "
            "users.last_login_at, users.max_devices, users.daily_job_limit, access_codes.id AS code_id, "
            "access_codes.hint, access_codes.created_at AS code_created_at, access_codes.expires_at AS code_expires_at, "
            "access_codes.last_used_at, access_codes.use_count, usage_daily.jobs AS jobs_today "
            "FROM users "
            "LEFT JOIN access_codes ON access_codes.id = ("
            "  SELECT id FROM access_codes AS latest WHERE latest.user_id = users.id AND latest.revoked_at IS NULL "
            "  ORDER BY latest.id DESC LIMIT 1) "
            "LEFT JOIN usage_daily ON usage_daily.user_id = users.id AND usage_daily.day = ? "
            "ORDER BY users.role = 'owner' DESC, users.created_at DESC",
            (day,),
        ).fetchall()
        sessions = connection.execute(
            "SELECT id, user_id, created_at, last_seen_at, user_agent, ip FROM sessions "
            "WHERE expires_at > ? ORDER BY last_seen_at DESC",
            (now,),
        ).fetchall()
    devices: dict[int, list[dict[str, Any]]] = {}
    for item in sessions:
        devices.setdefault(int(item["user_id"]), []).append(
            {
                "id": int(item["id"]),
                "created_at": int(item["created_at"]),
                "last_seen_at": int(item["last_seen_at"]),
                "device": describe_user_agent(item["user_agent"]),
                "ip": item["ip"],
            }
        )
    members = []
    for row in people:
        role = str(row["role"] or "member")
        members.append(
            {
                "id": int(row["id"]),
                "label": row["display_name"] or row["username"],
                "role": role,
                "state": _code_state(row, now),
                "created_at": int(row["created_at"]),
                "last_login_at": row["last_login_at"],
                "code": {
                    "hint": row["hint"],
                    "created_at": row["code_created_at"],
                    "expires_at": row["code_expires_at"],
                    "last_used_at": row["last_used_at"],
                    "use_count": int(row["use_count"] or 0),
                } if row["code_id"] is not None else None,
                "max_devices": device_limit(role, row["max_devices"]),
                "max_devices_override": row["max_devices"],
                "daily_job_limit": daily_job_limit(role, row["daily_job_limit"]),
                "daily_job_limit_override": row["daily_job_limit"],
                "jobs_today": int(row["jobs_today"] or 0),
                "devices": devices.get(int(row["id"]), []),
            }
        )
    return members


def describe_user_agent(value: str | None) -> str:
    agent = value or ""
    if not agent:
        return "未知设备"
    system = next(
        (
            name
            for pattern, name in (
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Android", "Android"),
                ("HarmonyOS", "鸿蒙"),
                ("Mac OS X", "Mac"),
                ("Macintosh", "Mac"),
                ("Windows", "Windows"),
                ("Linux", "Linux"),
            )
            if pattern in agent
        ),
        "未知系统",
    )
    browser = next(
        (
            name
            for pattern, name in (
                ("MicroMessenger", "微信"),
                ("QQ/", "QQ"),
                ("Edg/", "Edge"),
                ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"),
                ("Safari/", "Safari"),
            )
            if pattern in agent
        ),
        "浏览器",
    )
    return f"{system} · {browser}"


def gate_overview(limit: int = 60) -> dict[str, Any]:
    now = int(time.time())
    with connect() as connection:
        counts = {
            row["kind"]: int(row["total"])
            for row in connection.execute(
                "SELECT kind, COUNT(*) AS total FROM gate_events WHERE at > ? GROUP BY kind",
                (now - 86_400,),
            )
        }
        suspects = [
            row["ip"]
            for row in connection.execute(
                "SELECT DISTINCT ip FROM gate_events WHERE kind = 'denied' AND at > ?",
                (now - 86_400,),
            )
        ]
        locked = []
        for ip in suspects:
            remaining = _lock_remaining(connection, ip, now)
            if remaining:
                failures = connection.execute(
                    "SELECT COUNT(*) FROM gate_events WHERE ip = ? AND kind = 'denied' AND at > ?",
                    (ip, now - 86_400),
                ).fetchone()[0]
                locked.append({"ip": ip, "retry_after": remaining, "failures": int(failures)})
        events = connection.execute(
            "SELECT gate_events.at, gate_events.kind, gate_events.ip, gate_events.detail, "
            "users.display_name, users.username FROM gate_events "
            "LEFT JOIN users ON users.id = gate_events.user_id "
            "ORDER BY gate_events.id DESC LIMIT ?",
            (max(1, min(200, limit)),),
        ).fetchall()
    return {
        "summary": {
            "granted_24h": counts.get("granted", 0),
            "denied_24h": counts.get("denied", 0) + counts.get("forgiven", 0),
            "locked": sorted(locked, key=lambda item: -item["retry_after"]),
        },
        "events": [
            {
                "at": int(row["at"]),
                "kind": "denied" if row["kind"] == "forgiven" else row["kind"],
                "ip": row["ip"],
                "detail": row["detail"],
                "member": row["display_name"] or row["username"],
            }
            for row in events
        ],
    }


def unlock_address(ip: str) -> int:
    with connect() as connection:
        return connection.execute(
            "UPDATE gate_events SET kind = 'forgiven' WHERE ip = ? AND kind = 'denied'",
            (ip[:64],),
        ).rowcount


# ------------------------------------------------------------ command line


def _print_members() -> None:
    for member in list_members():
        code = member["code"] or {}
        print(
            f"{member['id']:>4}  {member['role']:<6}  {member['state']:<8}  "
            f"…{code.get('hint') or '----'}  devices {len(member['devices'])}/{member['max_devices']}  "
            f"{member['label']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.access", description="Manage activation codes.")
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue", help="issue a code (prints it once)")
    issue.add_argument("--label", required=True)
    issue.add_argument("--owner", action="store_true", help="grant owner rights")
    issue.add_argument("--username", help="bind to this existing account name")
    issue.add_argument("--days", type=int, help="expire after N days")
    issue.add_argument("--devices", type=int, help="max signed-in devices")
    commands.add_parser("list", help="list people and their codes")
    args = parser.parse_args(argv)
    initialize_auth_db()
    if args.command == "issue":
        code, _ = issue_code(
            label=args.label,
            role="owner" if args.owner else "member",
            username=args.username,
            expires_in_days=args.days,
            max_devices=args.devices,
        )
        print(code)
    else:
        _print_members()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
