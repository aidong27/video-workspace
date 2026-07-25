from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any


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
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

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
                seconds = max(0.0, float(actual_seconds or row[2]))
                safe_metadata = {
                    key: value
                    for key, value in (metadata or {}).items()
                    if key in {"provider", "model", "cache_hit", "fallback"}
                }
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
                        outcome[:32],
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
