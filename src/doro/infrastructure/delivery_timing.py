import sqlite3
import time

from doro.domain.work_delivery import DeliveryEvent, DeliveryTiming
from doro.infrastructure.storage import LocalStore, session_key


def initialize_timings(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS delivery_timings (input_id TEXT PRIMARY KEY, saved_at REAL, queued_at REAL, notified_at REAL, received_at REAL, acknowledged_at REAL)")


def record_timing(connection: sqlite3.Connection, note_id: str, event: DeliveryEvent) -> None:
    connection.execute("INSERT OR IGNORE INTO delivery_timings (input_id) VALUES (?)", (note_id,))
    column = event.value  # A closed enum, never a caller-provided SQL identifier.
    connection.execute(f"UPDATE delivery_timings SET {column}=COALESCE({column},?) WHERE input_id=?",
                       (time.time(), note_id))


def timing_for(store: LocalStore, note_id: str) -> DeliveryTiming:
    with store.connect() as connection:
        row = connection.execute("SELECT saved_at,queued_at,notified_at,received_at,acknowledged_at FROM delivery_timings WHERE input_id=?",
                                 (session_key(note_id),)).fetchone()
    values = [None if value is None else float(str(value)) for value in row] if row else []
    return DeliveryTiming(*values)
