import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.asr import usage as usage_module
from app.asr.base import TranscriptSegment
from app.asr.postprocess import normalize_segments
from app.asr.signing import SignedAudioError, SignedAudioStore
from app.asr.usage import UsageLedger, UsageLimitExceeded


class SignedAudioTests(unittest.TestCase):
    def test_signature_expiry_tampering_and_revocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "task" / "audio.mp3"
            audio.parent.mkdir()
            audio.write_bytes(b"audio")
            now = [1000.0]
            store = SignedAudioStore(
                root=root,
                public_base_url="https://caption.example.test",
                secret="s" * 32,
                clock=lambda: now[0],
            )
            token, url = store.register(audio, ttl_seconds=120)
            query = url.split("?", 1)[1]
            values = dict(item.split("=", 1) for item in query.split("&"))
            record = store.resolve(token, int(values["expires"]), values["signature"])
            self.assertEqual(record.path, audio.resolve())

            with self.assertRaises(SignedAudioError):
                store.resolve(token, int(values["expires"]), "0" * 64)
            store.revoke(token)
            with self.assertRaises(SignedAudioError):
                store.resolve(token, int(values["expires"]), values["signature"])

            token, url = store.register(audio, ttl_seconds=120)
            values = dict(item.split("=", 1) for item in url.split("?", 1)[1].split("&"))
            now[0] = 1201
            with self.assertRaises(SignedAudioError):
                store.resolve(token, int(values["expires"]), values["signature"])

    def test_outside_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / "audio.mp3"
            path.write_bytes(b"audio")
            store = SignedAudioStore(
                root=Path(temp),
                public_base_url="https://caption.example.test",
                secret="s" * 32,
            )
            with self.assertRaises(SignedAudioError):
                store.register(path)

    def test_public_base_url_must_be_a_clean_https_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for value in (
                "http://caption.example.test",
                "https://user:pass@caption.example.test",
                "https://caption.example.test/path",
                "https://caption.example.test?token=value",
            ):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    SignedAudioStore(
                        root=Path(temp),
                        public_base_url=value,
                        secret="s" * 32,
                    )


class UsageLedgerTests(unittest.TestCase):
    def test_reservations_enforce_global_and_user_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ledger = UsageLedger(
                Path(temp) / "usage.db",
                daily_limit_seconds=100,
                monthly_limit_seconds=120,
                user_daily_limit_seconds=60,
                clock=lambda: 1_700_000_000,
            )
            first = ledger.reserve(owner_key="user:1", model="qwen", predicted_seconds=40.2)
            with self.assertRaises(UsageLimitExceeded) as user_limit:
                ledger.reserve(owner_key="user:1", model="qwen", predicted_seconds=20)
            self.assertEqual(user_limit.exception.code, "asr_user_daily_limit_reached")

            second = ledger.reserve(owner_key="user:2", model="para", predicted_seconds=50)
            with self.assertRaises(UsageLimitExceeded) as daily_limit:
                ledger.reserve(owner_key="user:3", model="qwen", predicted_seconds=10)
            self.assertEqual(daily_limit.exception.code, "asr_daily_limit_reached")

            ledger.commit(
                first.reservation_id,
                actual_seconds=39.5,
                estimated_cost_cny=0.01,
                metadata={"provider": "aliyun", "secret": "not-stored"},
            )
            ledger.release(second.reservation_id)
            stats = ledger.stats()
            self.assertEqual(stats["daily_seconds"], 39.5)
            self.assertEqual(stats["reserved_seconds"], 0)
            self.assertEqual(stats["by_model_seconds"]["qwen"], 39.5)

    def test_failure_stats_aggregates_recent_failures_and_sanitizes_metadata(self) -> None:
        now = [1_700_000_000.0]
        with tempfile.TemporaryDirectory() as temp:
            ledger = UsageLedger(
                Path(temp) / "usage.db",
                daily_limit_seconds=1000,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=1000,
                clock=lambda: now[0],
            )

            now[0] -= 31 * 24 * 60 * 60
            old = ledger.reserve(owner_key="old-owner", model="old-model", predicted_seconds=10)
            ledger.commit(
                old.reservation_id,
                actual_seconds=10,
                estimated_cost_cny=0,
                outcome="provider_failed",
                metadata={"provider": "aliyun", "error_code": "old_failure"},
            )
            now[0] += 31 * 24 * 60 * 60

            first = ledger.reserve(
                owner_key="user:1",
                model="Qwen3-ASR-Flash",
                predicted_seconds=10,
            )
            ledger.commit(
                first.reservation_id,
                actual_seconds=10,
                estimated_cost_cny=0.01,
                outcome="Provider_Failed",
                metadata={
                    "provider": " AliYun ",
                    "model": " QWEN3-ASR-Flash ",
                    "error_code": " AllocationQuota.FreeTierOnly ",
                    "fallback": False,
                    "cache_hit": "false",
                    "message": "raw response must not be stored",
                    "url": "https://private.example.test/audio",
                    "body": "private response body",
                    "owner": "user:1",
                },
            )
            second = ledger.reserve(
                owner_key="user:2",
                model="ParaFormer-V2",
                predicted_seconds=20,
            )
            ledger.commit(
                second.reservation_id,
                actual_seconds=20,
                estimated_cost_cny=0.02,
                outcome="provider_internal_error",
                metadata={
                    "provider": "aliyun",
                    "model": "paraformer-v2",
                    "error_code": "ASR_TIMEOUT",
                    "fallback": True,
                },
            )
            completed = ledger.reserve(
                owner_key="user:3",
                model="ParaFormer-V2",
                predicted_seconds=5,
            )
            ledger.commit(
                completed.reservation_id,
                actual_seconds=5,
                estimated_cost_cny=0,
                metadata={
                    "provider": "aliyun",
                    "model": "paraformer-v2",
                    "error_code": "not_a_failure",
                },
            )

            with sqlite3.connect(ledger.path) as connection:
                stored_metadata = json.loads(
                    connection.execute(
                        "SELECT metadata_json FROM asr_usage_events WHERE reservation_id = ?",
                        (first.reservation_id,),
                    ).fetchone()[0]
                )
            self.assertEqual(
                stored_metadata,
                {
                    "provider": "aliyun",
                    "model": "qwen3-asr-flash",
                    "error_code": "allocationquota.freetieronly",
                    "fallback": False,
                },
            )
            self.assertEqual(
                ledger.failure_stats(),
                {
                    "window_days": 30,
                    "total": 2,
                    "by_provider": {"aliyun": 2},
                    "by_model": {"paraformer-v2": 1, "qwen3-asr-flash": 1},
                    "by_code": {
                        "allocationquota.freetieronly": 1,
                        "asr_timeout": 1,
                    },
                    "by_outcome": {
                        "provider_failed": 1,
                        "provider_internal_error": 1,
                    },
                },
            )

    def test_zero_usage_failure_event_does_not_consume_reserved_seconds(self) -> None:
        now = 1_700_000_000.0
        with tempfile.TemporaryDirectory() as temp:
            ledger = UsageLedger(
                Path(temp) / "usage.db",
                daily_limit_seconds=1000,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=1000,
                clock=lambda: now,
            )
            reservation = ledger.reserve(
                owner_key="user:1",
                model="Qwen3-ASR-Flash",
                predicted_seconds=30,
            )
            ledger.record_failure(
                provider=" AliYun ",
                model=" Qwen3-ASR-Flash ",
                error_code=" ASR_RATE_LIMITED ",
                outcome=" Provider_Failed ",
                reservation_id=reservation.reservation_id,
            )

            usage = ledger.stats()
            self.assertEqual(usage["daily_seconds"], 0)
            self.assertEqual(usage["reserved_seconds"], 0)
            self.assertEqual(
                ledger.failure_stats(),
                {
                    "window_days": 30,
                    "total": 1,
                    "by_provider": {"aliyun": 1},
                    "by_model": {"qwen3-asr-flash": 1},
                    "by_code": {"asr_rate_limited": 1},
                    "by_outcome": {"provider_failed": 1},
                },
            )

    def test_non_positive_committed_seconds_fall_back_to_reserved_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ledger = UsageLedger(
                Path(temp) / "usage.db",
                daily_limit_seconds=1000,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=1000,
            )
            reservation = ledger.reserve(
                owner_key="user:1",
                model="ParaFormer-V2",
                predicted_seconds=20,
            )
            ledger.commit(
                reservation.reservation_id,
                actual_seconds=0,
                estimated_cost_cny=0,
            )

            self.assertEqual(ledger.stats()["daily_seconds"], 20)

    def test_failure_event_retention_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.object(
            usage_module, "_FAILURE_EVENT_LIMIT", 3
        ):
            ledger = UsageLedger(
                Path(temp) / "usage.db",
                daily_limit_seconds=1000,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=1000,
            )
            for index in range(5):
                ledger.record_failure(
                    provider="aliyun",
                    model="qwen",
                    error_code=f"failure-{index}",
                    outcome="provider_failed",
                )

            with sqlite3.connect(ledger.path) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM asr_failure_events"
                ).fetchone()[0]
            self.assertEqual(count, 3)

    def test_failure_stats_bounds_legacy_labels_without_leaking_metadata(self) -> None:
        now = 1_700_000_000.0
        with tempfile.TemporaryDirectory() as temp:
            ledger = UsageLedger(
                Path(temp) / "usage.db",
                daily_limit_seconds=1000,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=1000,
                clock=lambda: now,
            )
            ledger.initialize()
            rows = [
                (
                    "legacy-malformed",
                    now - 1,
                    "https://private.example.test/model-token",
                    "provider_failed",
                    "{not-json",
                ),
                (
                    "legacy-malicious",
                    now - 2,
                    "private-owner@example.test",
                    "https://private.example.test/outcome-token",
                    json.dumps(
                        {
                            "provider": "https://private.example.test/provider-token",
                            "error_code": "raw response body token-123",
                            "owner": "private-owner@example.test",
                            "url": "https://private.example.test/audio-token",
                            "body": "raw response body token-123",
                        }
                    ),
                ),
                (
                    "legacy-list",
                    now - 3,
                    "ParaFormer-V2",
                    "PROVIDER_FAILED",
                    json.dumps(["private-owner@example.test"]),
                ),
                (
                    "outside-window",
                    now - 31 * 24 * 60 * 60,
                    "private-window-token",
                    "provider_failed",
                    json.dumps({"provider": "private-window-token"}),
                ),
            ]
            rows.extend(
                (
                    f"legacy-cardinality-{index}",
                    now - 10 - index,
                    f"model-{index:02d}",
                    f"failure-{index:02d}",
                    json.dumps(
                        {
                            "provider": f"provider-{index:02d}",
                            "error_code": f"error-{index:02d}",
                            "owner": "private-owner@example.test",
                        }
                    ),
                )
                for index in range(55)
            )
            with sqlite3.connect(ledger.path) as connection:
                connection.executemany(
                    """
                    INSERT INTO asr_usage_events (
                        reservation_id, created_at, day, month, owner_hash, model,
                        seconds, estimated_cost_cny, outcome, metadata_json
                    ) VALUES (?, ?, '2023-11-14', '2023-11', 'private-owner-hash', ?, 1, 0, ?, ?)
                    """,
                    rows,
                )

            stats = ledger.failure_stats()
            self.assertEqual(stats["window_days"], 30)
            self.assertEqual(stats["total"], 58)
            for dimension in ("by_provider", "by_model", "by_code", "by_outcome"):
                self.assertLessEqual(len(stats[dimension]), 50)
                self.assertEqual(sum(stats[dimension].values()), stats["total"])
            self.assertEqual(stats["by_provider"]["unknown"], 3)
            self.assertEqual(stats["by_code"]["unknown"], 3)
            serialized = json.dumps(stats, sort_keys=True)
            for secret in (
                "private.example.test",
                "private-owner",
                "raw response body",
                "token-123",
                "private-window-token",
            ):
                self.assertNotIn(secret, serialized)

    def test_lifetime_limit_does_not_reset_with_calendar_month(self) -> None:
        now = [1_700_000_000.0]
        with tempfile.TemporaryDirectory() as temp:
            ledger = UsageLedger(
                Path(temp) / "usage.db",
                daily_limit_seconds=1000,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=1000,
                total_limit_seconds=60,
                clock=lambda: now[0],
            )
            first = ledger.reserve(owner_key="user:1", model="qwen", predicted_seconds=40)
            ledger.commit(first.reservation_id, actual_seconds=40, estimated_cost_cny=0)
            now[0] += 40 * 24 * 60 * 60

            with self.assertRaises(UsageLimitExceeded) as total_limit:
                ledger.reserve(owner_key="user:1", model="qwen", predicted_seconds=21)

            self.assertEqual(total_limit.exception.code, "asr_total_limit_reached")


class TranscriptPostprocessTests(unittest.TestCase):
    def test_duplicate_segments_are_merged_and_long_text_is_split(self) -> None:
        segments = [
            TranscriptSegment(0, 1000, "重复"),
            TranscriptSegment(500, 1500, "重复"),
            TranscriptSegment(1600, 7000, "第一句话。第二句话很长，需要被拆开。第三句话。"),
            TranscriptSegment(-10, -1, "负时间"),
            TranscriptSegment(8000, 8500, "  "),
        ]
        output = normalize_segments(segments, max_chars=10)
        self.assertEqual(sum(item.text == "重复" for item in output), 1)
        self.assertTrue(all(item.text.strip() for item in output))
        self.assertTrue(all(item.start_ms >= 0 and item.end_ms > item.start_ms for item in output))
        self.assertTrue(all(left.end_ms <= right.start_ms for left, right in zip(output, output[1:])))
        self.assertGreater(sum("句话" in item.text for item in output), 1)


if __name__ == "__main__":
    unittest.main()
