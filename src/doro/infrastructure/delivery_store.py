import sqlite3

from doro.domain.models import DoroError, HumanInput
from doro.domain.work_delivery import DeliveryEvent, DeliveryState, WorkDelivery
from doro.infrastructure.delivery_timing import initialize_timings, record_timing
from doro.infrastructure.storage import LocalStore, session_key
from doro.infrastructure.serde import decode_session


def initialize_deliveries(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS work_deliveries (input_id TEXT PRIMARY KEY, state TEXT NOT NULL, queue_id TEXT NOT NULL, error TEXT NOT NULL)")
    initialize_timings(connection)
    connection.execute("CREATE TABLE IF NOT EXISTS input_notifications (input_id TEXT NOT NULL, turn_id TEXT NOT NULL, PRIMARY KEY(input_id,turn_id))")


def queue_delivery(connection: sqlite3.Connection, note_id: str) -> None:
    connection.execute("INSERT INTO work_deliveries VALUES (?,?,?,?)", (note_id, "pending", "", ""))
    record_timing(connection, note_id, DeliveryEvent.SAVED)


def received_delivery(connection: sqlite3.Connection, note_id: str) -> None:
    connection.execute("UPDATE work_deliveries SET state='received',error='' WHERE input_id=?", (note_id,))


def decode_delivery(row: tuple[object, ...]) -> WorkDelivery:
    return WorkDelivery(str(row[0]), DeliveryState(str(row[1])), str(row[2]), str(row[3]))


class DeliveryOutbox:
    def __init__(self, store: LocalStore) -> None:
        self.store = store

    def claim(self, note: HumanInput, retry: bool = False) -> tuple[WorkDelivery, bool]:
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            owner = connection.execute("SELECT thread_id FROM owners WHERE session_id=?", (note.session_id,)).fetchone()
            actual = connection.execute("SELECT owner_thread_id,state FROM user_inputs WHERE id=? AND session_id=?",
                                        (note.id, note.session_id)).fetchone()
            if not owner or not actual or str(owner[0]) != note.owner_thread_id or str(actual[0]) != note.owner_thread_id:
                raise DoroError("Work destination changed; no message was sent")
            row = connection.execute("SELECT * FROM work_deliveries WHERE input_id=?", (note.id,)).fetchone()
            if row is None:
                raise DoroError("No atomic delivery record exists for this input")
            delivery = decode_delivery(tuple(row))
            if str(actual[1]) == "read":
                received_delivery(connection, note.id)
                return WorkDelivery(note.id, DeliveryState.RECEIVED, delivery.queue_id), False
            if str(actual[1]) != "queued":
                raise DoroError("Input is no longer waiting; no Work was queued")
            allowed = {DeliveryState.PENDING, DeliveryState.FAILED} if retry else {DeliveryState.PENDING}
            if delivery.state not in allowed:
                return delivery, False
            if note.decision:
                row = connection.execute("SELECT payload FROM sessions WHERE id=?", (note.session_id,)).fetchone()
                if row is None:
                    raise DoroError("Approval session no longer exists")
                current = decode_session(str(row[0]))
                checkpoint = current.checkpoints[-1].id if current.status == "awaiting_approval" else ""
                if note.checkpoint_id != checkpoint:
                    connection.execute("UPDATE work_deliveries SET state='stale' WHERE input_id=?", (note.id,))
                    return WorkDelivery(note.id, DeliveryState.STALE), False
            connection.execute("UPDATE work_deliveries SET state='dispatching',error='' WHERE input_id=?", (note.id,))
        return WorkDelivery(note.id, DeliveryState.DISPATCHING), True

    def complete(self, note_id: str, state: DeliveryState, queue_id: str = "", error: str = "") -> WorkDelivery:
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute("UPDATE work_deliveries SET state=?,queue_id=?,error=? WHERE input_id=? AND state='dispatching'",
                                         (state.value, queue_id, error[:1000], session_key(note_id)))
            if state == DeliveryState.QUEUED:
                record_timing(connection, note_id, DeliveryEvent.QUEUED)
                connection.execute("UPDATE work_deliveries SET queue_id=? WHERE input_id=? AND state='received' AND queue_id=''",
                                   (queue_id, note_id))
            row = connection.execute("SELECT * FROM work_deliveries WHERE input_id=?", (note_id,)).fetchone()
            if row is None or (changed.rowcount != 1 and str(row[1]) != "received"):
                raise DoroError("Delivery state changed while sending; verify before retrying")
        return decode_delivery(tuple(row))

    def for_session(self, session_id: str) -> tuple[WorkDelivery, ...]:
        with self.store.connect() as connection:
            rows = connection.execute("SELECT d.* FROM work_deliveries d JOIN user_inputs i ON i.id=d.input_id WHERE i.session_id=?",
                                      (session_key(session_id),)).fetchall()
        return tuple(decode_delivery(tuple(row)) for row in rows)
