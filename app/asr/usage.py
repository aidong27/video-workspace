from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any, Iterator

from ..database import sqlite_connection


_FAILURE_LABEL_LIMIT = 50
_FAILURE_EVENT_LIMIT = 10_000
_FAILURE_RETENTION_SECONDS = 90 * 24 * 60 * 60
_METADATA_JSON_MAX_CHARS = 4096
_LABEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")


def _normalize_label(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if (
        not normalized
        or len(normalized) > max_length
        or not normalized.isascii()
        or _LABEL_PATTERN.fullmatch(normalized) is None
    ):
        return None
    return normalized


def _normalize_error_code(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    return _normalize_label(value, max_length=64)


def _safe_metadata(metadata_json: Any) -> dict[str, Any]:
    if not isinstance(metadata_json, str) or len(metadata_json) > _METADATA_JSON_MAX_CHARS:
        return {}
    try:
        metadata = json.loads(metadata_json)
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _bounded_counts(counts: dict[str, int]) -> dict[str, int]:
    if len(counts) <= _FAILURE_LABEL_LIMIT:
        return {label: counts[label] for label in sorted(counts)}
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    kept = dict(ranked[: _FAILURE_LABEL_LIMIT - 1])
    kept["other"] = kept.get("other", 0) + sum(
        count for _label, count in ranked[_FAILURE_LABEL_LIMIT - 1 :]
    )
    return {label: kept[label] for label in sorted(kept)}


class UsageLimitExceeded(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UsageReservation:
    reservation_id: str
    model: str
    seconds: int
    owner_hash: str
    created_at: float
    expires_at: float


def _periods(timestamp: float) -> tuple[str, str]:
    current = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return current.strftime("%Y-%m-%d"), current.strftime("%Y-%m")


class UsageLedger:
    def __init__(
        self,
        path: Path,
        *,
        daily_limit_seconds: int,
        monthly_limit_seconds: int,
        user_daily_limit_seconds: int,
        total_limit_seconds: int = 0,
        reservation_ttl_seconds: int = 7200,
        clock: callable = time.time,
    ) -> None:
        self.path = path
        self.daily_limit_seconds = max(0, int(daily_limit_seconds))
        self.monthly_limit_seconds = max(0, int(monthly_limit_seconds))
        self.user_daily_limit_seconds = max(0, int(user_daily_limit_seconds))
        self.total_limit_seconds = max(0, int(total_limit_seconds))
        self.reservation_ttl_seconds = max(60, int(reservation_ttl_seconds))
        self.clock = clock

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS asr_usage_events (
                    reservation_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    day TEXT NOT NULL,
                    month TEXT NOT NULL,
                    owner_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    seconds REAL NOT NULL,
                    estimated_cost_cny REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_asr_usage_day
                    ON asr_usage_events(day);
                CREATE INDEX IF NOT EXISTS idx_asr_usage_month
                    ON asr_usage_events(month);
                CREATE INDEX IF NOT EXISTS idx_asr_usage_created_at
                    ON asr_usage_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_asr_usage_owner_day
                    ON asr_usage_events(owner_hash, day);
                CREATE TABLE IF NOT EXISTS asr_usage_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    day TEXT NOT NULL,
                    month TEXT NOT NULL,
                    owner_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    seconds INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS asr_failure_events (
                    event_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    outcome TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_asr_failure_created_at
                    ON asr_failure_events(created_at);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with sqlite_connection(self.path, isolation_level=None) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            yield connection

    @staticmethod
    def owner_hash(owner_key: str) -> str:
        return hashlib.sha256(owner_key.encode("utf-8")).hexdigest()

    def reserve(self, *, owner_key: str, model: str, predicted_seconds: float) -> UsageReservation:
        now = float(self.clock())
        seconds = max(1, int(math.ceil(predicted_seconds)))
        day, month = _periods(now)
        owner_hash = self.owner_hash(owner_key)
        reservation = UsageReservation(
            secrets.token_hex(16),
            model,
            seconds,
            owner_hash,
            now,
            now + self.reservation_ttl_seconds,
        )
        self.initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "DELETE FROM asr_usage_reservations WHERE expires_at < ?",
                    (now,),
                )
                daily = self._sum_period(connection, "day", day)
                monthly = self._sum_period(connection, "month", month)
                user_daily = self._sum_owner_day(connection, owner_hash, day)
                total = self._sum_total(connection)
                if self.total_limit_seconds and total + seconds > self.total_limit_seconds:
                    raise UsageLimitExceeded(
                        "asr_total_limit_reached",
                        "云端语音识别总免费额度保护线已达到，未继续提交任务。",
                    )
                if self.daily_limit_seconds and daily + seconds > self.daily_limit_seconds:
                    raise UsageLimitExceeded(
                        "asr_daily_limit_reached",
                        "今日云端语音识别额度已用尽，未继续提交任务。",
                    )
                if self.monthly_limit_seconds and monthly + seconds > self.monthly_limit_seconds:
                    raise UsageLimitExceeded(
                        "asr_monthly_limit_reached",
                        "本月云端语音识别额度已用尽，未继续提交任务。",
                    )
                if self.user_daily_limit_seconds and user_daily + seconds > self.user_daily_limit_seconds:
                    raise UsageLimitExceeded(
                        "asr_user_daily_limit_reached",
                        "你今天可使用的云端语音识别时长已用尽。",
                    )
                connection.execute(
                    """
                    INSERT INTO asr_usage_reservations (
                        reservation_id, created_at, expires_at, day, month,
                        owner_hash, model, seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reservation.reservation_id,
                        reservation.created_at,
                        reservation.expires_at,
                        day,
                        month,
                        owner_hash,
                        model,
                        seconds,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return reservation

    @staticmethod
    def _sum_period(connection: sqlite3.Connection, column: str, value: str) -> float:
        committed = connection.execute(
            f"SELECT COALESCE(SUM(seconds), 0) FROM asr_usage_events WHERE {column} = ?",
            (value,),
        ).fetchone()[0]
        reserved = connection.execute(
            f"SELECT COALESCE(SUM(seconds), 0) FROM asr_usage_reservations WHERE {column} = ?",
            (value,),
        ).fetchone()[0]
        return float(committed or 0) + float(reserved or 0)

    @staticmethod
    def _sum_owner_day(connection: sqlite3.Connection, owner_hash: str, day: str) -> float:
        committed = connection.execute(
            """
            SELECT COALESCE(SUM(seconds), 0)
            FROM asr_usage_events
            WHERE owner_hash = ? AND day = ?
            """,
            (owner_hash, day),
        ).fetchone()[0]
        reserved = connection.execute(
            """
            SELECT COALESCE(SUM(seconds), 0)
            FROM asr_usage_reservations
            WHERE owner_hash = ? AND day = ?
            """,
            (owner_hash, day),
        ).fetchone()[0]
        return float(committed or 0) + float(reserved or 0)

    @staticmethod
    def _sum_total(connection: sqlite3.Connection) -> float:
        committed = connection.execute(
            "SELECT COALESCE(SUM(seconds), 0) FROM asr_usage_events"
        ).fetchone()[0]
        reserved = connection.execute(
            "SELECT COALESCE(SUM(seconds), 0) FROM asr_usage_reservations"
        ).fetchone()[0]
        return float(committed or 0) + float(reserved or 0)

    def commit(
        self,
        reservation_id: str,
        *,
        actual_seconds: float,
        estimated_cost_cny: float,
        outcome: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.initialize()
        now = float(self.clock())
        day, month = _periods(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT owner_hash, model, seconds
                    FROM asr_usage_reservations
                    WHERE reservation_id = ?
                    """,
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return
                seconds = float(actual_seconds)
                if not math.isfinite(seconds) or seconds <= 0:
                    seconds = float(row[2])
                metadata = metadata if isinstance(metadata, dict) else {}
                safe_metadata: dict[str, Any] = {}
                provider = _normalize_label(metadata.get("provider"), max_length=32)
                model = _normalize_label(metadata.get("model"), max_length=64)
                error_code = _normalize_error_code(metadata.get("error_code"))
                if provider is not None:
                    safe_metadata["provider"] = provider
                if model is not None:
                    safe_metadata["model"] = model
                if error_code is not None:
                    safe_metadata["error_code"] = error_code
                for key in ("cache_hit", "fallback"):
                    if isinstance(metadata.get(key), bool):
                        safe_metadata[key] = metadata[key]
                safe_outcome = _normalize_label(outcome, max_length=32) or "unknown"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO asr_usage_events (
                        reservation_id, created_at, day, month, owner_hash, model,
                        seconds, estimated_cost_cny, outcome, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        now,
                        day,
                        month,
                        row[0],
                        row[1],
                        seconds,
                        max(0.0, float(estimated_cost_cny)),
                        safe_outcome,
                        json.dumps(safe_metadata, ensure_ascii=True, separators=(",", ":")),
                    ),
                )
                connection.execute(
                    "DELETE FROM asr_usage_reservations WHERE reservation_id = ?",
                    (reservation_id,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def release(self, reservation_id: str) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM asr_usage_reservations WHERE reservation_id = ?",
                (reservation_id,),
            )

    def record_failure(
        self,
        *,
        provider: Any,
        model: Any,
        error_code: Any,
        outcome: Any,
        reservation_id: str | None = None,
    ) -> None:
        """Release a reservation and record a bounded, zero-usage failure event."""
        self.initialize()
        now = float(self.clock())
        safe_provider = _normalize_label(provider, max_length=32) or "unknown"
        safe_model = _normalize_label(model, max_length=64) or "unknown"
        safe_error_code = _normalize_error_code(error_code) or "unknown"
        safe_outcome = _normalize_label(outcome, max_length=32) or "unknown"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if reservation_id:
                    connection.execute(
                        "DELETE FROM asr_usage_reservations WHERE reservation_id = ?",
                        (reservation_id,),
                    )
                connection.execute(
                    "DELETE FROM asr_failure_events WHERE created_at < ?",
                    (now - _FAILURE_RETENTION_SECONDS,),
                )
                connection.execute(
                    """
                    INSERT INTO asr_failure_events (
                        event_id, created_at, provider, model, error_code, outcome
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        secrets.token_hex(16),
                        now,
                        safe_provider,
                        safe_model,
                        safe_error_code,
                        safe_outcome,
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM asr_failure_events
                    WHERE event_id IN (
                        SELECT event_id
                        FROM asr_failure_events
                        ORDER BY created_at DESC, event_id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (_FAILURE_EVENT_LIMIT,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def stats(self) -> dict[str, Any]:
        self.initialize()
        now = float(self.clock())
        day, month = _periods(now)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM asr_usage_reservations WHERE expires_at < ?",
                (now,),
            )
            daily = self._sum_period(connection, "day", day)
            monthly = self._sum_period(connection, "month", month)
            total = self._sum_total(connection)
            reserved = connection.execute(
                "SELECT COALESCE(SUM(seconds), 0) FROM asr_usage_reservations"
            ).fetchone()[0]
            by_model_rows = connection.execute(
                """
                SELECT model, COALESCE(SUM(seconds), 0)
                FROM asr_usage_events
                WHERE month = ?
                GROUP BY model
                """,
                (month,),
            ).fetchall()
        return {
            "daily_seconds": round(daily, 3),
            "monthly_seconds": round(monthly, 3),
            "total_seconds": round(total, 3),
            "reserved_seconds": int(reserved or 0),
            "daily_limit_seconds": self.daily_limit_seconds,
            "monthly_limit_seconds": self.monthly_limit_seconds,
            "user_daily_limit_seconds": self.user_daily_limit_seconds,
            "total_limit_seconds": self.total_limit_seconds,
            "by_model_seconds": {str(model): round(float(seconds), 3) for model, seconds in by_model_rows},
        }

    def failure_stats(self, window_days: int = 30) -> dict[str, Any]:
        self.initialize()
        try:
            normalized_window_days = int(window_days)
        except (TypeError, ValueError):
            normalized_window_days = 30
        normalized_window_days = max(1, normalized_window_days)
        now = float(self.clock())
        cutoff = now - normalized_window_days * 24 * 60 * 60
        with self._connect() as connection:
            usage_rows = connection.execute(
                """
                SELECT model, outcome, metadata_json
                FROM asr_usage_events
                WHERE created_at BETWEEN ? AND ?
                """,
                (cutoff, now),
            ).fetchall()
            failure_rows = connection.execute(
                """
                SELECT provider, model, error_code, outcome
                FROM asr_failure_events
                WHERE created_at BETWEEN ? AND ?
                """,
                (cutoff, now),
            ).fetchall()

        counts: dict[str, dict[str, int]] = {
            "provider": {},
            "model": {},
            "code": {},
            "outcome": {},
        }
        total = 0
        for stored_model, stored_outcome, metadata_json in usage_rows:
            outcome = _normalize_label(stored_outcome, max_length=32) or "unknown"
            if outcome == "completed":
                continue
            metadata = _safe_metadata(metadata_json)
            provider = _normalize_label(metadata.get("provider"), max_length=32) or "unknown"
            model = _normalize_label(stored_model, max_length=64) or "unknown"
            error_code = _normalize_error_code(metadata.get("error_code")) or "unknown"
            labels = {
                "provider": provider,
                "model": model,
                "code": error_code,
                "outcome": outcome,
            }
            total += 1
            for dimension, label in labels.items():
                dimension_counts = counts[dimension]
                dimension_counts[label] = dimension_counts.get(label, 0) + 1

        for stored_provider, stored_model, stored_error_code, stored_outcome in failure_rows:
            labels = {
                "provider": _normalize_label(stored_provider, max_length=32) or "unknown",
                "model": _normalize_label(stored_model, max_length=64) or "unknown",
                "code": _normalize_error_code(stored_error_code) or "unknown",
                "outcome": _normalize_label(stored_outcome, max_length=32) or "unknown",
            }
            total += 1
            for dimension, label in labels.items():
                dimension_counts = counts[dimension]
                dimension_counts[label] = dimension_counts.get(label, 0) + 1

        return {
            "window_days": normalized_window_days,
            "total": total,
            "by_provider": _bounded_counts(counts["provider"]),
            "by_model": _bounded_counts(counts["model"]),
            "by_code": _bounded_counts(counts["code"]),
            "by_outcome": _bounded_counts(counts["outcome"]),
        }
