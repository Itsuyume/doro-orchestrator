from doro.domain.models import Config, DoroError, HumanInput, Session, Task, Turn
from doro.infrastructure.delivery_store import queue_delivery
from doro.infrastructure.new_task_store import NewTaskStore
from doro.infrastructure.serde import encode_session
from doro.infrastructure.storage import session_key


def attach_chat(store: NewTaskStore, request_id: str, owner: str, thread_id: str, config: Config) -> str:
    request, note = store.input(request_id, owner)
    session_key(thread_id)
    if owner != request.broker_thread or thread_id == owner:
        raise DoroError("A newly created GPT chat is required; the broker cannot own the task")
    if request.state == "created" and request.thread_id == thread_id:
        return request.session_id
    if request.state not in {"creating", "unknown"}:
        raise DoroError("Task creation was not claimed, or its outcome is already recorded")
    task = Task("GPT chat connection; external review requires a separate approved public scope.", "public", ("codex",), "")
    session = Session(request.session_id, task, config.fingerprint, ("work",), 1,
                      status="chat_active", mode="chat")
    copied = HumanInput(request.child_input_id, session.id, thread_id, note.text, 0, "")
    label = " ".join(note.text.split())[:40]
    with store.sessions.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT session_id FROM owners WHERE thread_id=?", (thread_id,)).fetchone():
            raise DoroError("The target GPT chat already owns another task")
        changed = connection.execute("UPDATE new_tasks SET state='created',thread_id=?,error='' WHERE id=? AND state IN ('creating','unknown')",
                                     (thread_id, request.id))
        if changed.rowcount != 1:
            raise DoroError("Task creation changed concurrently")
        connection.execute("INSERT INTO sessions VALUES (?,?)", (session.id, encode_session(session)))
        connection.execute("INSERT INTO owners VALUES (?,?,?)", (session.id, thread_id, label))
        connection.execute("INSERT INTO user_inputs VALUES (?,?,?,?,?,?,?,?,?)",
            (copied.id, copied.session_id, copied.owner_thread_id, copied.text, copied.after_turn,
             copied.checkpoint_id, copied.state, copied.decision, copied.response))
        queue_delivery(connection, copied.id)
    return session.id


def update_chat(store: NewTaskStore, request_id: str, owner: str, text: str, final: bool) -> str:
    request, _ = store.input(request_id, owner)
    if request.state != "created" or owner != request.thread_id:
        raise DoroError("Only the new owning GPT chat can publish its response")
    if not text.strip() or len(text) > 6000 or "\0" in text:
        raise DoroError("GPT reply must contain 1-6000 characters without NUL")
    with store.sessions.lock(request.session_id):
        session = store.sessions.load(request.session_id)
        if session.mode != "chat":
            raise DoroError("Fresh-task replies require a chat-only route")
        phase = "final" if final else "progress"
        turn = Turn("work", phase, text, 0, None, owner)
        if not session.turns or session.turns[-1] != turn:
            session.turns.append(turn)
        session.status = "completed" if final else "chat_active"
        store.sessions.save(session)
    note = store.inputs.get(request.child_input_id)
    if note.state == "queued":
        store.inputs.acknowledge(note.id, owner)
    return request.session_id
