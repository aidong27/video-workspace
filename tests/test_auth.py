import contextlib
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from app import access, auth


class AccessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "auth" / "auth.db"
        self.env = patch.dict(os.environ, {"AUTH_DB_PATH": str(self.db), "ACCESS_CODE_PEPPER": ""})
        self.env.start()
        auth.initialize_auth_db()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def deny(self, ip: str, count: int, at: int) -> None:
        with auth.connect() as connection:
            for _ in range(count):
                connection.execute(
                    "INSERT INTO gate_events(at, kind, ip, detail) VALUES (?, 'denied', ?, 'unknown')", (at, ip)
                )


class CodeFormatTests(AccessTestCase):
    def test_generated_codes_are_grouped_crockford_base32(self) -> None:
        codes = {access.generate_code() for _ in range(200)}
        self.assertEqual(len(codes), 200)
        for code in codes:
            self.assertRegex(code, r"^[0-9A-HJKMNP-TV-Z]{5}(-[0-9A-HJKMNP-TV-Z]{5}){3}$")

    def test_normalization_forgives_case_separators_and_confusable_letters(self) -> None:
        self.assertEqual(access.normalize_code("abcde fghjk-mnpqr_stvwx"), "ABCDEFGHJKMNPQRSTVWX")
        self.assertEqual(access.normalize_code("O0OOO-IIIII-LLLLL-00000"), "00000111111111100000")
        for bad in ("", "ABCDE", "ABCDE-FGHJK-MNPQR-STVWXY", "ABCDE-FGHJK-MNPQR-STVWU", None):
            self.assertIsNone(access.normalize_code(bad))

    def test_digest_depends_on_the_server_pepper(self) -> None:
        normalized = "ABCDEFGHJKMNPQRSTVWX"
        first = access.code_digest(normalized)
        pepper_file = self.db.parent / "access-pepper"
        self.assertEqual(oct(pepper_file.stat().st_mode & 0o777), "0o600")
        self.assertEqual(len(pepper_file.read_bytes()), 32)
        with patch.dict(os.environ, {"ACCESS_CODE_PEPPER": "p" * 40}):
            self.assertNotEqual(access.code_digest(normalized), first)
        self.assertEqual(access.code_digest(normalized), first)


class ActivationTests(AccessTestCase):
    def test_issue_and_activate_creates_a_bound_session(self) -> None:
        code, user_id = access.issue_code(label="小王")
        result = access.activate(code, "198.51.100.7", "Mozilla/5.0 (iPhone) Safari/604.1")
        self.assertEqual((result.user.user_id, result.user.label, result.user.role), (user_id, "小王", "member"))
        self.assertEqual(auth.resolve_session(result.token), result.user)
        members = access.list_members()
        self.assertEqual(members[0]["devices"][0]["device"], "iPhone · Safari")
        self.assertEqual(members[0]["devices"][0]["ip"], "198.51.100.7")
        self.assertEqual(members[0]["code"]["use_count"], 1)

    def test_failures_lock_an_address_with_escalating_durations(self) -> None:
        now = int(time.time())
        self.deny("192.0.2.1", 5, now)
        with self.assertRaises(auth.AuthFailure) as locked:
            access.activate("ABCDE-FGHJK-MNPQR-STVWX", "192.0.2.1")
        self.assertEqual(locked.exception.reason, "gate_locked")
        self.assertGreater(locked.exception.extra["retry_after"], 850)

        self.deny("192.0.2.2", 10, now - 1000)
        with self.assertRaises(auth.AuthFailure) as hour:
            access.activate("ABCDE-FGHJK-MNPQR-STVWX", "192.0.2.2")
        self.assertGreater(hour.exception.extra["retry_after"], 2500)

        self.deny("192.0.2.3", 20, now - 5000)
        with self.assertRaises(auth.AuthFailure) as day:
            access.activate("ABCDE-FGHJK-MNPQR-STVWX", "192.0.2.3")
        self.assertGreater(day.exception.extra["retry_after"], 80_000)

        # Old failures outside every window no longer count.
        self.deny("192.0.2.4", 9, now - 90_000)
        with self.assertRaises(auth.AuthFailure) as fresh:
            access.activate("ABCDE-FGHJK-MNPQR-STVWX", "192.0.2.4")
        self.assertEqual(fresh.exception.reason, "invalid_code")

    def test_a_successful_entry_forgives_the_address(self) -> None:
        code, _ = access.issue_code(label="小李")
        for _ in range(3):
            with self.assertRaises(auth.AuthFailure):
                access.activate("ABCDE-FGHJK-MNPQR-STVWX", "203.0.113.5")
        access.activate(code, "203.0.113.5")
        with self.assertRaises(auth.AuthFailure) as after:
            access.activate("ABCDE-FGHJK-MNPQR-STVWX", "203.0.113.5")
        self.assertEqual(after.exception.extra["attempts_left"], 4)

    def test_owner_bootstrap_binds_to_an_existing_account(self) -> None:
        with auth.connect() as connection:
            connection.execute(
                "INSERT INTO users(id, username, password_salt, password_hash, created_at) VALUES (4, 'aidong27', x'00', x'00', 1)"
            )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            access.main(["issue", "--owner", "--username", "aidong27", "--label", "站长"])
        code = stdout.getvalue().strip()
        result = access.activate(code, "127.0.0.1")
        self.assertEqual((result.user.user_id, result.user.role, result.user.label), (4, "owner", "站长"))
        self.assertTrue(auth.is_admin_user(result.user))
        self.assertIsNone(access.quota_status(4)["limit"])
        with self.assertRaises(auth.AuthFailure):
            access.update_member(4, active=False)
        with self.assertRaises(auth.AuthFailure):
            access.delete_member(4)


class QuotaTests(AccessTestCase):
    def test_daily_quota_resets_at_china_midnight_and_refunds(self) -> None:
        _, user_id = access.issue_code(label="小张", daily_job_limit=2)
        before_midnight = 1_767_196_799  # 2025-12-31 23:59:59 +08:00
        access.consume_job_quota(user_id, now=before_midnight)
        access.consume_job_quota(user_id, now=before_midnight)
        with self.assertRaises(auth.AuthFailure) as spent:
            access.consume_job_quota(user_id, now=before_midnight)
        self.assertEqual(spent.exception.reason, "daily_quota_reached")
        self.assertEqual(spent.exception.extra["retry_after"], 1)
        access.refund_job_quota(user_id, now=before_midnight)
        access.consume_job_quota(user_id, now=before_midnight)
        access.consume_job_quota(user_id, now=before_midnight + 1)
        self.assertEqual(access.quota_status(user_id, now=before_midnight + 1)["used"], 1)

    def test_limit_defaults_and_overrides(self) -> None:
        self.assertIsNone(access.daily_job_limit("owner", 5))
        self.assertIsNone(access.daily_job_limit("member", 0))
        self.assertEqual(access.daily_job_limit("member", 7), 7)
        with patch.dict(os.environ, {"MEMBER_DAILY_JOB_LIMIT": "12"}):
            self.assertEqual(access.daily_job_limit("member", None), 12)
        with patch.dict(os.environ, {"MEMBER_DAILY_JOB_LIMIT": "0"}):
            self.assertIsNone(access.daily_job_limit("member", None))
        self.assertEqual(auth.device_limit("member", None), 3)
        self.assertEqual(auth.device_limit("owner", None), 10)
        self.assertEqual(auth.device_limit("member", 1), 1)


class MigrationTests(unittest.TestCase):
    def test_password_era_database_upgrades_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.db"
            legacy = sqlite3.connect(path)
            legacy.executescript(
                """
                CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at INTEGER NOT NULL,
                    last_login_at INTEGER, is_active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id)
                    ON DELETE CASCADE, token_hash BLOB NOT NULL UNIQUE, created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL);
                INSERT INTO users VALUES (4, 'aidong27', x'00', x'00', 1, NULL, 1);
                INSERT INTO sessions VALUES (1, 4, x'01', 1, 99999999999, 1);
                """
            )
            legacy.commit()
            legacy.close()
            with patch.dict(os.environ, {"AUTH_DB_PATH": str(path)}):
                auth.initialize_auth_db()
                auth.initialize_auth_db()
                with auth.connect() as connection:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
                    self.assertTrue({"code_id", "user_agent", "ip"} <= columns)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
                    self.assertEqual(
                        connection.execute("SELECT username, role FROM users").fetchall()[0][:], ("aidong27", "member")
                    )
                self.assertIsNone(auth.resolve_session("anything"))


class CookieTests(unittest.TestCase):
    def test_secure_cookies_use_the_host_prefix(self) -> None:
        with patch.dict(os.environ, {"AUTH_COOKIE_SECURE": "true"}):
            self.assertEqual(auth.session_cookie_name(), "__Host-caption_session")
        with patch.dict(os.environ, {"AUTH_COOKIE_SECURE": "false"}):
            self.assertEqual(auth.session_cookie_name(), "caption_session")

    def test_user_agents_are_summarized_without_storing_detail(self) -> None:
        self.assertEqual(
            access.describe_user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/130.0 Safari/537.36"),
            "Mac · Chrome",
        )
        self.assertEqual(access.describe_user_agent("Mozilla/5.0 (Linux; Android 14) MicroMessenger/8.0"), "Android · 微信")
        self.assertEqual(access.describe_user_agent(None), "未知设备")


if __name__ == "__main__":
    unittest.main()
