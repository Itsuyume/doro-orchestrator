from dataclasses import replace
import hashlib
import secrets
import sqlite3
import time

from doro.domain.models import DoroError, HUMAN_INPUT_LIMIT, HumanInput
from doro.domain.validation import string
from doro.infrastructure.serde import decode_session
from doro.infrastructure.storage import LocalStore, session_key
from doro.infrastructure.delivery_store import initialize_deliveries, queue_delivery, received_delivery
from doro.infrastructure.delivery_timing import record_timing
from doro.domain.work_delivery import DeliveryEvent


def authorize_ui(connection: sqlite3.Connection, session_id: str, token: str) -> None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = connection.execute("SELECT session_id FROM ui_tokens WHERE digest=? AND expires>?", (digest, time.time())).fetchone()
    if not row or row[0] != session_id:
        raise DoroError("Native input instance is missing, expired or bound to another collaboration")


def decode_input(row: tuple[object, ...]) -> HumanInput:
    return HumanInput(str(row[0]), str(row[1]), str(row[2]), str(row[3]), int(str(row[4])),
                      str(row[5]), str(row[6]), str(row[7]), str(row[8]))


class LocalInputStore:
    """UI-origin control messages only; never calls a model or changes an approval."""
    def __init__(self, sessions: LocalStore) -> None:
        self.sessions = sessions
        with sessions.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS ui_tokens (digest TEXT PRIMARY KEY, session_id TEXT NOT NULL, expires REAL NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS user_inputs (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, owner_thread_id TEXT NOT NULL, text TEXT NOT NULL, after_turn INTEGER NOT NULL, checkpoint_id TEXT NOT NULL, state TEXT NOT NULL, decision TEXT NOT NULL, response TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS pending_work_inputs ON user_inputs(owner_thread_id,state)")
            initialize_deliveries(connection)

    def register_ui(self, session_id: str) -> str:
        session_key(session_id)
        if not any(route.session_id == session_id for route in self.sessions.routes()):
            raise DoroError("Register the owning Work before enabling native input")
        token = secrets.token_urlsafe(32)
        with self.sessions.connect() as connection:
            connection.execute("DELETE FROM ui_tokens WHERE expires<?", (time.time(),))
            connection.execute("INSERT INTO ui_tokens VALUES (?,?,?)",
                               (hashlib.sha256(token.encode()).hexdigest(), session_id, time.time() + 86400))
        return token

    def post(self, session_id: str, text: str, checkpoint_id: str, token: str,
             client_id: str, decision: str = "") -> HumanInput:
        session_key(session_id)
        session_key(client_id)
        string(text, "human input")
        if len(text) > HUMAN_INPUT_LIMIT or "\0" in text or decision not in {"", "approve", "reject"}:
            raise DoroError(f"Human input must be within {HUMAN_INPUT_LIMIT} characters without NUL")
        with self.sessions.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            authorize_ui(connection, session_id, token)
            existing = connection.execute("SELECT * FROM user_inputs WHERE id=?", (client_id,)).fetchone()
            if existing:
                return verify_repost(decode_input(tuple(existing)), session_id, text, checkpoint_id, decision)
            row = connection.execute("SELECT payload FROM sessions WHERE id=?", (session_id,)).fetchone()
            owner = connection.execute("SELECT thread_id FROM owners WHERE session_id=?", (session_id,)).fetchone()
            if row is None or owner is None:
                raise DoroError("The owning Work or collaboration is no longer available")
            session = decode_session(str(row[0]))
            current = session.checkpoints[-1].id if session.status == "awaiting_approval" else ""
            if checkpoint_id != current:
                raise DoroError("The displayed approval changed; refresh and send again")
            if decision and not current:
                raise DoroError("No unanswered approval exists; ordinary chat cannot grant permission")
            duplicate = connection.execute("SELECT id FROM user_inputs WHERE session_id=? AND checkpoint_id=? AND decision!=''",
                                           (session_id, current)).fetchone()
            if decision and duplicate:
                raise DoroError("An answer for this question is already waiting for Work; no second decision was queued")
            note = HumanInput(client_id, session.id, str(owner[0]), text, len(session.turns), current, decision=decision)
            connection.execute("INSERT INTO user_inputs VALUES (?,?,?,?,?,?,?,?,?)",
                               (note.id, note.session_id, note.owner_thread_id, note.text, note.after_turn, note.checkpoint_id,
                                note.state, note.decision, note.response))
            queue_delivery(connection, note.id)
        return note

    def get(self, note_id: str) -> HumanInput:
        with self.sessions.connect() as connection:
            row = connection.execute("SELECT * FROM user_inputs WHERE id=?", (session_key(note_id),)).fetchone()
        if row is None:
            raise DoroError("Human input not found")
        return decode_input(tuple(row))

    def inputs(self, session_id: str) -> tuple[HumanInput, ...]:
        with self.sessions.connect() as connection:
            rows = connection.execute("SELECT * FROM user_inputs WHERE session_id=? ORDER BY rowid", (session_key(session_id),)).fetchall()
        return tuple(decode_input(tuple(row)) for row in rows)

    def receive(self, note_id: str, owner: str) -> HumanInput:
        with self.sessions.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT i.* FROM user_inputs i JOIN owners o ON o.session_id=i.session_id WHERE i.id=? AND i.owner_thread_id=? AND o.thread_id=?",
                                     (session_key(note_id), session_key(owner), owner)).fetchone()
            if row is None:
                raise DoroError("Only the registered owning Work can receive this input")
            note = decode_input(tuple(row))
            received_delivery(connection, note.id)
            if note.state != "read":
                record_timing(connection, note.id, DeliveryEvent.RECEIVED)
        return note

    def pending(self, session_id: str, owner: str) -> tuple[HumanInput, ...]:
        routes = {route.session_id: route.thread_id for route in self.sessions.routes()}
        if routes.get(session_id) != session_key(owner):
            raise DoroError("Human input must be read by its registered owning Work")
        return tuple(self.receive(note.id, owner) for note in self.inputs(session_id) if note.state == "queued")

    def acknowledge(self, note_id: str, owner: str, response: str = "") -> HumanInput:
        if len(response) > 6000:
            raise DoroError("Work response exceeds its 6000-character bound")
        with self.sessions.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM user_inputs WHERE id=?", (session_key(note_id),)).fetchone()
            if row is None:
                raise DoroError("Human input not found")
            note = decode_input(tuple(row))
            if note.owner_thread_id != session_key(owner):
                raise DoroError("Only the owning Work can acknowledge this human input")
            connection.execute("UPDATE user_inputs SET state='read',response=? WHERE id=?", (response, note_id))
            received_delivery(connection, note_id)
            if note.state != "read":
                record_timing(connection, note_id, DeliveryEvent.RECEIVED)
                record_timing(connection, note_id, DeliveryEvent.ACKNOWLEDGED)
        return replace(note, state="read", response=response)


def verify_repost(note: HumanInput, session_id: str, text: str, checkpoint: str, decision: str) -> HumanInput:
    if (note.session_id, note.text, note.checkpoint_id, note.decision) != (session_id, text, checkpoint, decision):
        raise DoroError("Input UUID was reused with different content; no duplicate was accepted")
    return note
