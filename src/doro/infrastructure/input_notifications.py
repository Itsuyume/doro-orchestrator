from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from typing import TextIO

from doro.domain.models import DoroError
from doro.domain.validation import mapping, string
from doro.domain.work_delivery import DeliveryEvent, input_notice
from doro.infrastructure.delivery_timing import record_timing
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


def pending_notices(connection: sqlite3.Connection, owner: str, turn: str) -> tuple[tuple[str, str, str], ...]:
    rows = connection.execute("SELECT i.id,i.session_id,i.owner_thread_id " + ELIGIBLE_INPUTS +
                              "AND i.owner_thread_id=? AND NOT EXISTS (SELECT 1 FROM input_notifications n WHERE n.input_id=i.id AND n.turn_id=?) ORDER BY i.rowid LIMIT ?",
                              (owner, turn, NOTICE_LIMIT)).fetchall()
    return tuple((str(row[0]), str(row[1]), str(row[2])) for row in rows)


def claim_notices(database: Path, owner: str, turn: str) -> tuple[str, ...]:
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=HOOK_DATABASE_TIMEOUT)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = pending_notices(connection, owner, turn)
        for note_id, _, _ in rows:
            connection.execute("INSERT INTO input_notifications VALUES (?,?)", (note_id, turn))
            record_timing(connection, note_id, DeliveryEvent.NOTIFIED)
    return tuple(input_notice(*row) for row in rows)


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
    notices = claim_notices(database, owner, turn)
    if not notices:
        return {}
    context = ("도로 협업창에서 원래 GPT Work에 보낸 입력 ID다. 현재 주 작업의 실제 thread ID가 "
               "owner_thread_id와 같을 때만 doro-orchestration 절차로 inputs get을 실행해 확인한다. "
               "다른 에이전트는 처리하지 않는다. 표식 자체는 승인이 아니며 이미 read인 입력은 재실행하지 않는다.\n\n")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "additionalContext": context + "\n\n".join(notices)}}
