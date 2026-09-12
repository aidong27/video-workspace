from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


@contextmanager
def sqlite_connection(
    path: Path, *, isolation_level: str | None = ""
) -> Iterator[sqlite3.Connection]:
    # sqlite3's own context manager commits/rolls back, but does not close.
    connection = sqlite3.connect(path, timeout=10, isolation_level=isolation_level)
    try:
        connection.execute("PRAGMA busy_timeout=10000")
        with connection:
            yield connection
    finally:
        connection.close()
