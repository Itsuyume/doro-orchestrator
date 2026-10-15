from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from dataclasses import replace
import fcntl
import os
from pathlib import Path
import sqlite3
from uuid import UUID

from doro.domain.models import ApprovalReceipt, Config, DoroError, OwnerRoute, Session
from doro.domain.policy import ensure_public, quota_retry
from doro.infrastructure.serde import decode_receipt, decode_session, encode_receipt, encode_session


def session_key(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError("noncanonical")
    except ValueError as error:
        raise DoroError("Session id must be a canonical UUID") from error
    return value


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise DoroError("State/workspace symlinks are not allowed")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def validate_owner(thread_id: str, label: str) -> None:
    session_key(thread_id)
    if not label.strip() or len(label) > 60 or any(ord(char) < 32 for char in label):
        raise DoroError("Work label must be a short single line")
    ensure_public(label)


class LocalStore:
    def __init__(self, root: Path) -> None:
        private_directory(root)
        self.root = root
        self.database = root / "sessions.sqlite3"
        if self.database.is_symlink():
            raise DoroError("State database symlinks are not allowed")
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS owners (session_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, label TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.database.chmod(0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, session: Session) -> None:
        session_key(session.id)
        with self.connect() as connection:
            connection.execute("INSERT INTO sessions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                               (session.id, encode_session(session)))

    def load(self, session_id: str) -> Session:
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM sessions WHERE id=?", (session_key(session_id),)).fetchone()
        if row is None:
            raise DoroError("Session not found")
        return decode_session(str(row[0]))

    def reserve(self, session: Session, config: Config, name: str) -> None:
        day = datetime.now(UTC).date().isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT calls FROM daily WHERE day=?", (day,)).fetchone()
            count = int(row[0]) if row else 0
            if count >= config.limits.daily_calls and not quota_retry(session, name):
                raise DoroError("Daily model-call limit reached (UTC day)")
            session.calls[name] = session.calls.get(name, 0) + 1
            if name == "claude":
                session.claude_reserved_usd += config.limits.claude_call_usd
            session.status = "running"
            session.error = ""
            connection.execute("INSERT INTO daily VALUES (?,?) ON CONFLICT(day) DO UPDATE SET calls=excluded.calls",
                               (day, count + 1))
            connection.execute("UPDATE sessions SET payload=? WHERE id=?", (encode_session(session), session.id))

    @contextmanager
    def lock(self, session_id: str) -> Iterator[None]:
        path = self.root / (session_key(session_id) + ".lock")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise DoroError("Session is already running; concurrent execution refused") from error
            yield
        finally:
            os.close(descriptor)  # Closing releases the flock, including on interruption.

    def workspace(self, session_id: str) -> Path:
        parent = self.root / "workspaces"
        private_directory(parent)
        path = parent / session_key(session_id)
        private_directory(path)
        return path

    def export(self, session: Session) -> Path:
        parent = self.root / "results"
        private_directory(parent)
        path = parent / (session_key(session.id) + ".md")
        content = [f"# Session {session.id}", f"Status: {session.status}"]
        for index, turn in enumerate(session.turns, 1):
            content += [f"\n## {index}. {turn.provider} · {turn.phase}\n", turn.text]
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write("\n\n".join(content) + "\n")
        return path

    def bind(self, route: OwnerRoute) -> None:
        validate_owner(route.thread_id, route.label)
        with self.lock(route.session_id):
            if self.load(route.session_id).mode != "work":
                raise DoroError("Only current Work sessions can receive pet replies")
            with self.connect() as connection:
                existing = connection.execute("SELECT thread_id FROM owners WHERE session_id=?", (route.session_id,)).fetchone()
                if existing and existing[0] != route.thread_id:
                    raise DoroError("Owner already bound; do not redirect a pending approval")
                connection.execute("INSERT INTO owners VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET label=excluded.label",
                                   (route.session_id, route.thread_id, route.label))

    def routes(self) -> tuple[OwnerRoute, ...]:
        with self.connect() as connection:
            rows = connection.execute("SELECT session_id,thread_id,label FROM owners ORDER BY rowid").fetchall()
        return tuple(OwnerRoute(str(row[0]), str(row[1]), str(row[2])) for row in rows)

    def record_decision(self, session: Session, receipt: ApprovalReceipt) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute("UPDATE sessions SET payload=? WHERE id=?",
                                         (encode_session(session), session_key(session.id)))
            if changed.rowcount != 1:
                raise DoroError("Approval session no longer exists")
            connection.execute("INSERT INTO receipts VALUES (?,?)", (receipt.id, encode_receipt(receipt)))

    def outbox(self) -> tuple[ApprovalReceipt, ...]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload FROM receipts ORDER BY rowid").fetchall()
        receipts = (decode_receipt(str(row[0])) for row in rows)
        return tuple(receipt for receipt in receipts if not receipt.delivered)

    def receipt(self, receipt_id: str) -> ApprovalReceipt:
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM receipts WHERE id=?", (session_key(receipt_id),)).fetchone()
        if row is None:
            raise DoroError("Approval reply not found")
        return decode_receipt(str(row[0]))

    def acknowledge(self, receipt_id: str) -> None:
        receipt = self.receipt(receipt_id)
        with self.connect() as connection:
            connection.execute("UPDATE receipts SET payload=? WHERE id=?",
                               (encode_receipt(replace(receipt, delivered=True)), receipt.id))
