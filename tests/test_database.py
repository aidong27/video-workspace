import sqlite3

import pytest

from app import auth
from app.asr.usage import UsageLedger
from app.database import sqlite_connection
from app.jobs import JobManager


def test_connection_commits_rolls_back_and_always_closes(tmp_path):
    path = tmp_path / "state.db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE example (value INTEGER)")
        connection.execute("INSERT INTO example VALUES (1)")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with pytest.raises(RuntimeError), sqlite_connection(path) as failed:
        failed.execute("INSERT INTO example VALUES (2)")
        raise RuntimeError("transaction failed")
    with pytest.raises(sqlite3.ProgrammingError):
        failed.execute("SELECT 1")
    with sqlite_connection(path) as reopened:
        assert reopened.execute("SELECT value FROM example").fetchall() == [(1,)]


def test_application_connectors_close_and_preserve_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    manager = JobManager(lambda request, update: request, state_path=tmp_path / "jobs.db")
    ledger = UsageLedger(
        tmp_path / "usage.db", daily_limit_seconds=100,
        monthly_limit_seconds=100, user_daily_limit_seconds=100,
    )
    for _ in range(3):
        with auth._connect() as connection:
            assert connection.row_factory == sqlite3.Row
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with manager._connect_state() as connection:
            assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with ledger._connect() as connection:
            assert connection.isolation_level is None
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


def test_autocommit_connection_preserves_explicit_rollback(tmp_path):
    with sqlite_connection(tmp_path / "auto.db", isolation_level=None) as connection:
        connection.execute("CREATE TABLE example (value INTEGER)")
        connection.execute("INSERT INTO example VALUES (1)")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO example VALUES (2)")
        connection.execute("ROLLBACK")
        assert connection.execute("SELECT value FROM example").fetchall() == [(1,)]
