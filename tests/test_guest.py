from __future__ import annotations

import base64
import unittest

from app.guest import GuestMediaRateLimiter, GuestSessionCodec


class GuestSessionTests(unittest.TestCase):
    def test_signed_session_rejects_tampering_and_expiry(self) -> None:
        codec = GuestSessionCodec("s" * 32, ttl_seconds=600)
        token, identity = codec.issue(now=1_000)

        resolved = codec.resolve(token, now=1_599)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.owner_id, identity.owner_id)
        self.assertLess(identity.owner_id, 0)
        self.assertIsNone(codec.resolve(token, now=1_600))

        payload, signature = token.split(".", 1)
        replacement = "A" if signature[-1] != "A" else "B"
        self.assertIsNone(codec.resolve(f"{payload}.{signature[:-1]}{replacement}", now=1_100))

        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        canonical_index = alphabet.index(signature[-1])
        noncanonical_signature = f"{signature[:-1]}{alphabet[canonical_index + 1]}"
        padding = "=" * (-len(signature) % 4)
        alias_padding = "=" * (-len(noncanonical_signature) % 4)
        self.assertEqual(
            base64.urlsafe_b64decode(signature + padding),
            base64.urlsafe_b64decode(noncanonical_signature + alias_padding),
        )
        self.assertIsNone(codec.resolve(f"{payload}.{noncanonical_signature}", now=1_100))

    def test_short_secret_disables_guest_sessions(self) -> None:
        codec = GuestSessionCodec("too-short", ttl_seconds=600)
        self.assertFalse(codec.enabled)
        self.assertIsNone(codec.resolve("anything"))
        with self.assertRaises(RuntimeError):
            codec.issue()


class GuestRateLimitTests(unittest.TestCase):
    def test_session_and_global_limits_have_retry_windows(self) -> None:
        limiter = GuestMediaRateLimiter(
            session_limit=2,
            global_limit=3,
            window_seconds=60,
        )
        self.assertIsNone(limiter.consume(-1, now=100))
        self.assertIsNone(limiter.consume(-1, now=101))
        session_limit = limiter.consume(-1, now=102)
        self.assertIsNotNone(session_limit)
        self.assertEqual(session_limit.reason, "guest_media_session_limit")
        self.assertGreater(session_limit.retry_after_seconds, 0)

        self.assertIsNone(limiter.consume(-2, now=102))
        global_limit = limiter.consume(-3, now=103)
        self.assertIsNotNone(global_limit)
        self.assertEqual(global_limit.reason, "guest_media_global_limit")
        self.assertIsNone(limiter.consume(-3, now=161))


if __name__ == "__main__":
    unittest.main()
