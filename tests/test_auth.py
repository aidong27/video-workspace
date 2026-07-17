import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.auth import (
    AuthFailure,
    authenticate_user,
    create_session,
    delete_session,
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


if __name__ == "__main__":
    unittest.main()
