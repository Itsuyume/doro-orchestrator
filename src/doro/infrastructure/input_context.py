import sqlite3

from doro.domain.input_context import input_context
from doro.domain.models import HumanInput
from doro.infrastructure.input_store import decode_input


def render_inputs(connection: sqlite3.Connection, notes: tuple[HumanInput, ...]) -> str:
    """The new-task table is optional in older stores; never initialize it from a hook."""
    lookup: frozenset[str] = frozenset()
    table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='new_tasks'").fetchone()
    if table is not None and notes:
        placeholders = ",".join("?" for _ in notes)
        rows = connection.execute(f"SELECT id FROM new_tasks WHERE id IN ({placeholders})",
                                  tuple(note.id for note in notes)).fetchall()
        lookup = frozenset(str(row[0]) for row in rows)
    return input_context(notes, lookup)


def queued_context(connection: sqlite3.Connection, note: str, session: str, owner: str) -> str:
    row = connection.execute(
        "SELECT i.* FROM user_inputs i JOIN owners o ON o.session_id=i.session_id "
        "JOIN work_deliveries d ON d.input_id=i.id WHERE i.id=? AND i.session_id=? "
        "AND i.owner_thread_id=? AND o.thread_id=? AND i.state='queued' "
        "AND d.state IN ('dispatching','queued','unknown','received')",
        (note, session, owner, owner),
    ).fetchone()
    return render_inputs(connection, (decode_input(tuple(row)),)) if row is not None else ""
