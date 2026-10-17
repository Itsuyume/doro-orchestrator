from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from typing import TextIO

from doro.domain.models import DoroError, HumanInput
from doro.domain.validation import mapping, string
from doro.domain.work_delivery import DeliveryEvent
from doro.infrastructure.delivery_timing import record_timing
from doro.infrastructure.input_context import render_inputs
from doro.infrastructure.input_store import decode_input
from doro.infrastructure.storage import session_key

NOTICE_LIMIT = 5
HOOK_INPUT_LIMIT = 1_048_576
HOOK_DATABASE_TIMEOUT = 0.1
REQUIRED_TABLES = {"owners", "user_inputs", "work_deliveries", "delivery_timings", "input_notifications"}
ELIGIBLE_INPUTS = ("FROM user_inputs i JOIN owners o ON o.session_id=i.session_id "
                   "JOIN work_deliveries d ON d.input_id=i.id "
                   "WHERE i.owner_thread_id=o.thread_id AND i.state='queued' "
                   "AND d.state IN ('dispatching','queued','unknown') ")


def has_pending(connection: sqlite3.Connection) -> bool:
    tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not REQUIRED_TABLES <= tables:
        return False
    return connection.execute("SELECT 1 " + ELIGIBLE_INPUTS + "LIMIT 1").fetchone() is not None


def hook_scope(payload: object, actual_owner: str | None) -> tuple[str, str] | None:
    """Bind trusted Codex events; the shell-tool thread environment is optional for hooks."""
    data = mapping(payload, "hook input")
    # Codex PostToolUse includes these fields only for subagents, whose session_id can be their parent's.
    if data.get("hook_event_name") != "PostToolUse" or "agent_id" in data or "agent_type" in data:
        return None
    owner = session_key(string(data.get("session_id"), "hook session"))
    if actual_owner is not None and actual_owner != owner:
        return None
    turn = string(data.get("turn_id"), "hook turn")
    if len(turn) > 200 or any(ord(char) < 32 for char in turn):
        raise DoroError("Hook turn must be a bounded opaque identifier without control characters")
    return owner, turn


def pending_notices(connection: sqlite3.Connection, owner: str, turn: str) -> tuple[HumanInput, ...]:
    rows = connection.execute("SELECT i.* " + ELIGIBLE_INPUTS +
                              "AND i.owner_thread_id=? AND NOT EXISTS (SELECT 1 FROM input_notifications n WHERE n.input_id=i.id AND n.turn_id=?) ORDER BY i.rowid LIMIT ?",
                              (owner, turn, NOTICE_LIMIT)).fetchall()
    return tuple(decode_input(tuple(row)) for row in rows)


def claim_notices(database: Path, owner: str, turn: str) -> str:
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=HOOK_DATABASE_TIMEOUT)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = pending_notices(connection, owner, turn)
        context = render_inputs(connection, rows)
        for note in rows:
            connection.execute("INSERT INTO input_notifications VALUES (?,?)", (note.id, turn))
            record_timing(connection, note.id, DeliveryEvent.NOTIFIED)
    return context


def hook_notice(state: Path, actual_owner: str | None, incoming: TextIO = sys.stdin) -> dict[str, object]:
    text = incoming.read(HOOK_INPUT_LIMIT + 1)
    database = state / "sessions.sqlite3"
    if not database.is_file():
        return {}
    if state.is_symlink() or database.is_symlink():
        raise DoroError("Input notification state cannot be a symlink")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=HOOK_DATABASE_TIMEOUT)) as connection:
        if not has_pending(connection):
            return {}
        if len(text) > HOOK_INPUT_LIMIT:
            raise DoroError("Input notification skipped: hook payload exceeds its size limit; the official queue is unchanged")
        scope = hook_scope(json.loads(text), actual_owner)
        if scope is None:
            return {}
        owner, turn = scope
        if not pending_notices(connection, owner, turn):
            return {}
    context = claim_notices(database, owner, turn)
    if not context:
        return {}
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "additionalContext": context}}
