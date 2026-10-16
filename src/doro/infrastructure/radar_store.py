"""Delivery deduplication only; never writes the plugin's synchronization ledger."""
from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from doro.domain.models import DoroError
from doro.domain.validation import integer, mapping
from doro.infrastructure.storage import private_directory


class RadarJournal:
    def __init__(self, connection: sqlite3.Connection, owner: str) -> None:
        self.connection = connection
        connection.execute("CREATE TABLE IF NOT EXISTS binding (owner TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS cache (id INTEGER PRIMARY KEY, checked REAL, versions TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, changes TEXT, state TEXT, receipt TEXT, error TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, event_id TEXT NOT NULL)")
        prior = connection.execute("SELECT owner FROM binding").fetchone()
        if prior and prior[0] != owner:
            raise DoroError("Radar delivery owner changed; inspect the existing journal")
        if not prior:
            connection.execute("INSERT INTO binding VALUES (?)", (owner,))
        connection.commit()

    def cached(self) -> tuple[float, dict[str, int]]:
        row = self.connection.execute("SELECT checked,versions FROM cache WHERE id=1").fetchone()
        if row is None:
            return 0, {}
        raw = mapping(json.loads(str(row[1])), "cached Page versions")
        return float(row[0]), {key: integer(value, "cached sequence", low=0, high=2**63 - 1)
                              for key, value in raw.items()}

    def cache(self, checked: float, versions: dict[str, int]) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO cache VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET checked=excluded.checked,versions=excluded.versions",
                                    (checked, json.dumps(versions, sort_keys=True)))

    def claim(self, changes: tuple[str, ...]) -> tuple[str, tuple[str, ...]] | None:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            known = {str(row[0]) for row in self.connection.execute("SELECT token FROM tokens")}
            active = set(changes)
            self.connection.executemany("DELETE FROM tokens WHERE token=?", ((token,) for token in known - active))
            known &= active
            if known:
                return None  # The existing Work will re-read the full current change set.
            fresh = tuple(change for change in changes if change not in known)
            if not fresh:
                return None
            event = str(uuid4())
            self.connection.execute("INSERT INTO events VALUES (?,?,'dispatching','','')", (event, json.dumps(fresh)))
            self.connection.executemany("INSERT INTO tokens VALUES (?,?)", ((token, event) for token in fresh))
            return event, fresh

    def complete(self, event: str, state: str, receipt: str = "", error: str = "") -> None:
        with self.connection:
            self.connection.execute("UPDATE events SET state=?,receipt=?,error=? WHERE id=?",
                                    (state, receipt, error, event))

    def status(self) -> dict[str, object]:
        rows = self.connection.execute("SELECT id,state,receipt,error FROM events ORDER BY rowid DESC LIMIT 20")
        return {"events": [{"id": str(r[0]), "state": str(r[1]), "queue_id": str(r[2]), "error": str(r[3])}
                           for r in rows]}


@contextmanager
def journal(root: Path, owner: str) -> Iterator[RadarJournal]:
    private_directory(root)
    descriptor = os.open(root / "detector.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DoroError("Radar inspection already running; duplicate execution refused") from error
        path = root / "detector.sqlite3"
        if path.is_symlink():
            raise DoroError("Radar journal cannot be a symlink")
        connection = sqlite3.connect(path)
        try:
            path.chmod(0o600)
            yield RadarJournal(connection, owner)
        finally:
            connection.close()
    finally:
        os.close(descriptor)


def save_report(path: Path, value: dict[str, object]) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise DoroError("Radar report cannot replace a symlink")
    temporary = path.with_name(".status-" + str(uuid4()))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
