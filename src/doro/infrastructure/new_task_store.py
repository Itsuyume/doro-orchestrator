import hashlib
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from doro.domain.models import DoroError, HUMAN_INPUT_LIMIT, HumanInput
from doro.domain.new_tasks import NewTaskRequest
from doro.domain.validation import string
from doro.infrastructure.input_store import LocalInputStore, authorize_ui
from doro.infrastructure.storage import LocalStore, session_key


class NewTaskStore:
    def __init__(self, sessions: LocalStore) -> None:
        self.sessions = sessions
        self.inputs = LocalInputStore(sessions)
        with sessions.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS new_tasks (id TEXT PRIMARY KEY, source_session TEXT NOT NULL, broker_thread TEXT NOT NULL, text_hash TEXT NOT NULL, state TEXT NOT NULL, thread_id TEXT NOT NULL, session_id TEXT NOT NULL, child_input_id TEXT NOT NULL, error TEXT NOT NULL)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS new_task_threads ON new_tasks(thread_id) WHERE thread_id!=''")

    def begin(self, source: str, text: str, client_id: str, token: str) -> NewTaskRequest:
        session_key(source)
        session_key(client_id)
        string(text, "new task")
        if len(text) > HUMAN_INPUT_LIMIT or "\0" in text:
            raise DoroError("New task input exceeds its character bound or contains NUL")
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.sessions.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            authorize_ui(connection, source, token)
            owner = connection.execute("SELECT thread_id FROM owners WHERE session_id=?", (source,)).fetchone()
            if owner is None:
                raise DoroError("A registered GPT chat is required to create a fresh task")
            existing = connection.execute("SELECT * FROM new_tasks WHERE id=?", (client_id,)).fetchone()
            if existing:
                request = decode_request(existing)
                if (request.source_session, request.broker_thread, request.text_hash) != (source, str(owner[0]), digest):
                    raise DoroError("New task ID was already used for different input")
                return request
            if connection.execute("SELECT id FROM user_inputs WHERE id=?", (client_id,)).fetchone():
                raise DoroError("An existing reply cannot become a fresh-task request")
            request = NewTaskRequest(client_id, source, str(owner[0]), digest, "pending", "",
                str(uuid5(NAMESPACE_URL, client_id + "/chat")), str(uuid5(NAMESPACE_URL, client_id + "/input")), "")
            connection.execute("INSERT INTO new_tasks VALUES (?,?,?,?,?,?,?,?,?)",
                (request.id, request.source_session, request.broker_thread, request.text_hash, request.state,
                 request.thread_id, request.session_id, request.child_input_id, request.error))
        return request

    def get(self, request_id: str) -> NewTaskRequest:
        request = self.find(request_id)
        if request is None:
            raise DoroError("New task request not found")
        return request

    def find(self, request_id: str) -> NewTaskRequest | None:
        with self.sessions.connect() as connection:
            row = connection.execute("SELECT * FROM new_tasks WHERE id=?", (session_key(request_id),)).fetchone()
        return decode_request(row) if row is not None else None

    def input(self, request_id: str, owner: str) -> tuple[NewTaskRequest, HumanInput]:
        request = self.get(request_id)
        if session_key(owner) not in {request.broker_thread, request.thread_id}:
            raise DoroError("New task request belongs to another GPT chat")
        note = self.inputs.get(request.id)
        routes = {route.session_id: route.thread_id for route in self.sessions.routes()}
        if routes.get(request.source_session) != request.broker_thread:
            raise DoroError("New task source owner changed")
        if (note.session_id, note.owner_thread_id) != (request.source_session, request.broker_thread):
            raise DoroError("New task source owner changed")
        if hashlib.sha256(note.text.encode()).hexdigest() != request.text_hash or note.decision:
            raise DoroError("New task input does not match the explicit UI request")
        return request, note

    def claim(self, request_id: str, owner: str) -> bool:
        request, _ = self.input(request_id, owner)
        if request.broker_thread != owner:
            raise DoroError("Only the receiving GPT can claim task creation")
        with self.sessions.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return connection.execute("UPDATE new_tasks SET state='creating' WHERE id=? AND state='pending'",
                                      (request.id,)).rowcount == 1

    def failed(self, request_id: str, owner: str, error: str, uncertain: bool) -> None:
        request, _ = self.input(request_id, owner)
        if request.broker_thread != owner or request.state != "creating":
            raise DoroError("Only an in-flight creation can record a failure")
        string(error, "creation failure")
        if len(error) > 2000:
            raise DoroError("Creation failure exceeds its bound")
        with self.sessions.connect() as connection:
            changed = connection.execute("UPDATE new_tasks SET state=?,error=? WHERE id=? AND state='creating'",
                                         ("unknown" if uncertain else "failed", error, request.id))
            if changed.rowcount != 1:
                raise DoroError("Task creation outcome changed concurrently")


def decode_request(row: sqlite3.Row | tuple[object, ...]) -> NewTaskRequest:
    return NewTaskRequest(*(str(value) for value in row))
