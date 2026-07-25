import tempfile
import unittest
from pathlib import Path

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
