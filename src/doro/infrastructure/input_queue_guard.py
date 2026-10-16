from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from typing import TextIO

from doro.domain.models import DoroError
from doro.domain.validation import mapping
from doro.domain.work_delivery import DeliveryState, parse_input_notice

GUARD_INPUT_LIMIT = 1_048_576
GUARD_DATABASE_TIMEOUT = 0.1
GUARD_TABLES = {"owners", "user_inputs", "work_deliveries"}


def guard_notice(state: Path, actual_owner: str | None, incoming: TextIO = sys.stdin) -> dict[str, object]:
    """Stop handled queue envelopes before Codex persists a prompt or calls the model."""
    text = incoming.read(GUARD_INPUT_LIMIT + 1)
    if len(text) > GUARD_INPUT_LIMIT:
        return {}  # Cannot prove this is a bounded transport envelope; preserve the prompt.
    data = mapping(json.loads(text), "hook input")
    if data.get("hook_event_name") != "UserPromptSubmit" or "agent_id" in data or "agent_type" in data:
        return {}
    notice = parse_input_notice(data.get("prompt"))
    if notice is None:
        return {}
    note, session, owner = notice
    if data.get("session_id") != owner or (actual_owner is not None and actual_owner != owner):
        return {}
    database = state / "sessions.sqlite3"
    if not database.is_file():
        return {}
    if state.is_symlink() or database.is_symlink():
        raise DoroError("Duplicate-input guard state cannot be a symlink")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True,
                                 timeout=GUARD_DATABASE_TIMEOUT)) as connection:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not GUARD_TABLES <= tables:
            return {}
        handled = connection.execute(
            "SELECT 1 FROM user_inputs i JOIN owners o ON o.session_id=i.session_id "
            "JOIN work_deliveries d ON d.input_id=i.id "
            "WHERE i.id=? AND i.session_id=? AND i.owner_thread_id=? AND o.thread_id=? "
            "AND i.state='read' AND d.state=?", (note, session, owner, owner, DeliveryState.RECEIVED.value),
        ).fetchone()
    # No reason/context/warning: handled transport envelopes need no further model reply.
    return {"continue": False} if handled is not None else {}
