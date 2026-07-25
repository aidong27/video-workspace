import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.auth import (
    AuthFailure,
    account_summary,
    authenticate_user,
    change_password,
    create_session,
    delete_session,
    delete_user_sessions,
    initialize_auth_db,
    register_user,
    resolve_session,
    user_count,
)


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "auth.db"
        self.invite_code = "permanent-test-code"
        self.environment = patch.dict(
            os.environ,
            {
                "AUTH_DB_PATH": str(self.db_path),
                "AUTH_MAX_USERS": "50",
                "AUTH_SESSION_TTL_DAYS": "30",
                "AUTH_MAX_SESSIONS_PER_USER": "8",
                "INVITE_CODE_HASH": hashlib.sha256(self.invite_code.encode()).hexdigest(),
            },
            clear=False,
        )
        self.environment.start()
        initialize_auth_db()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_register_login_and_session_lifecycle(self) -> None:
        user = register_user("Friend_01", "a-long-password", self.invite_code)
        logged_in = authenticate_user("friend_01", "a-long-password")
        self.assertEqual(logged_in.user_id, user.user_id)
        self.assertEqual(logged_in.username, "Friend_01")

        token, expires_at = create_session(logged_in)
        self.assertGreater(expires_at, 0)
        self.assertEqual(resolve_session(token), logged_in)
        delete_session(token)
        self.assertIsNone(resolve_session(token))

    def test_invite_code_and_password_are_not_stored_in_plaintext(self) -> None:
        password = "private-password-123"
        register_user("private_user", password, self.invite_code)

        raw_database = self.db_path.read_bytes()
        self.assertNotIn(password.encode(), raw_database)
        self.assertNotIn(self.invite_code.encode(), raw_database)
        with sqlite3.connect(self.db_path) as connection:
            password_hash = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertEqual(len(password_hash), 32)

    def test_invalid_invite_and_duplicate_username_are_rejected(self) -> None:
        with self.assertRaises(AuthFailure) as invalid_invite:
            register_user("friend_one", "a-long-password", "wrong-code")
        self.assertEqual(invalid_invite.exception.reason, "invalid_invite_code")

        register_user("friend_one", "a-long-password", self.invite_code)
        with self.assertRaises(AuthFailure) as duplicate:
            register_user("FRIEND_ONE", "another-password", self.invite_code)
        self.assertEqual(duplicate.exception.reason, "username_taken")

    def test_wrong_credentials_are_rejected_generically(self) -> None:
        register_user("friend_two", "a-long-password", self.invite_code)
        for username, password in (
            ("friend_two", "wrong-password"),
            ("missing_user", "wrong-password"),
        ):
            with self.assertRaises(AuthFailure) as failure:
                authenticate_user(username, password)
            self.assertEqual(failure.exception.reason, "invalid_credentials")
            self.assertEqual(failure.exception.message, "用户名或密码不正确。")

    def test_user_limit_is_enforced(self) -> None:
        os.environ["AUTH_MAX_USERS"] = "1"
        register_user("first_user", "a-long-password", self.invite_code)
        self.assertEqual(user_count(), 1)
        with self.assertRaises(AuthFailure) as failure:
            register_user("second_user", "a-long-password", self.invite_code)
        self.assertEqual(failure.exception.reason, "user_limit_reached")

    def test_password_change_revokes_existing_sessions(self) -> None:
        user = register_user("secure_user", "old-password-123", self.invite_code)
        first_token, _ = create_session(user)
        second_token, _ = create_session(user)

        updated = change_password(user.user_id, "old-password-123", "new-password-456")

        self.assertEqual(updated.user_id, user.user_id)
        self.assertIsNone(resolve_session(first_token))
        self.assertIsNone(resolve_session(second_token))
        with self.assertRaises(AuthFailure):
            authenticate_user("secure_user", "old-password-123")
        self.assertEqual(
            authenticate_user("secure_user", "new-password-456").user_id,
            user.user_id,
        )

    def test_password_change_rejects_wrong_and_reused_passwords(self) -> None:
        user = register_user("password_user", "current-password", self.invite_code)
        with self.assertRaises(AuthFailure) as wrong:
            change_password(user.user_id, "wrong-password", "replacement-password")
        self.assertEqual(wrong.exception.reason, "current_password_invalid")

        with self.assertRaises(AuthFailure) as unchanged:
            change_password(user.user_id, "current-password", "current-password")
        self.assertEqual(unchanged.exception.reason, "password_unchanged")

    def test_session_cap_prunes_oldest_sessions_and_logout_all_clears_them(self) -> None:
        os.environ["AUTH_MAX_SESSIONS_PER_USER"] = "2"
        user = register_user("session_user", "session-password", self.invite_code)
        first_token, _ = create_session(user)
        second_token, _ = create_session(user)
        third_token, _ = create_session(user)

        self.assertIsNone(resolve_session(first_token))
        self.assertIsNotNone(resolve_session(second_token))
        self.assertIsNotNone(resolve_session(third_token))
        self.assertEqual(account_summary(user.user_id)["active_sessions"], 2)
        delete_user_sessions(user.user_id)
        self.assertEqual(account_summary(user.user_id)["active_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
