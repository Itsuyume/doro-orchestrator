"""Local screen-use leases; caller holds the database transaction during cleanup."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Cursor state cannot use symlinks")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    connection = sqlite3.connect(path, timeout=0.2)
    path.chmod(0o600)
    try:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS leases (session TEXT, turn TEXT, PRIMARY KEY(session,turn))")
            connection.execute("CREATE TABLE IF NOT EXISTS audit (created TEXT DEFAULT CURRENT_TIMESTAMP, result TEXT)")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
    finally:
        connection.close()


def begin(connection: sqlite3.Connection, session: str, turn: str) -> None:
    connection.execute("INSERT OR IGNORE INTO leases VALUES (?,?)", (session, turn))


def release(connection: sqlite3.Connection, session: str, turn: str | None) -> bool:
    if turn is None:
        changed = connection.execute("DELETE FROM leases WHERE session=?", (session,)).rowcount
    else:
        changed = connection.execute("DELETE FROM leases WHERE session=? AND turn=?", (session, turn)).rowcount
    return changed > 0


def remaining(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) FROM leases").fetchone()
    assert row is not None
    return int(row[0])


def active(connection: sqlite3.Connection) -> list[dict[str, str]]:
    return [{"session": str(row[0]), "turn": str(row[1])} for row in connection.execute("SELECT session,turn FROM leases")]


def record(connection: sqlite3.Connection, status: str, before: int, after: int) -> dict[str, str | int]:
    result: dict[str, str | int] = {"status": status, "before": before, "after": after}
    connection.execute("INSERT INTO audit(result) VALUES (?)", (json.dumps(result),))
    connection.execute("DELETE FROM audit WHERE rowid NOT IN (SELECT rowid FROM audit ORDER BY rowid DESC LIMIT 1000)")
    return result
