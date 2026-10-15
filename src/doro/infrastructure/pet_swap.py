from collections.abc import Callable
from dataclasses import asdict
import json

from doro.domain.models import DoroError, PetSwap
from doro.domain.pet_swap import activate_swap, finish_restore, prepare_swap, release_swap
from doro.domain.validation import keys, mapping, string, strings
from doro.infrastructure.storage import LocalStore, session_key


def decode_swap(payload: str) -> PetSwap:
    data = mapping(json.loads(payload), "pet swap")
    keys(data, {"original_pet_id", "sessions", "stage"}, "pet swap")
    sessions = () if data["sessions"] == [] else strings(data["sessions"], "display leases")
    for session in sessions:
        session_key(session)
    state = PetSwap(string(data["original_pet_id"], "original pet"), sessions, string(data["stage"], "swap stage"))
    if state.stage not in {"prepared", "active", "restoring", "restored", "superseded"}:
        raise DoroError("Unknown pet swap stage")
    if bool(state.sessions) != (state.stage in {"prepared", "active"}):
        raise DoroError("Pet swap display leases do not match the recorded stage")
    return state


class PetSwapLedger:
    """Local display leases; never changes a pet selection or calls a model."""
    def __init__(self, store: LocalStore) -> None:
        self.store = store
        with store.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS pet_swap (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")

    def current(self) -> PetSwap | None:
        with self.store.connect() as connection:
            row = connection.execute("SELECT payload FROM pet_swap WHERE id=1").fetchone()
        return decode_swap(str(row[0])) if row else None

    def change(self, action: str, session_id: str = "", owner: str = "", observed: str = "") -> PetSwap:
        if action != "restored":
            routes = {route.session_id: route.thread_id for route in self.store.routes()}
            if routes.get(session_key(session_id)) != session_key(owner):
                raise DoroError("Only the registered owning Work can change this display lease")
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM pet_swap WHERE id=1").fetchone()
            state = decode_swap(str(row[0])) if row else None
            result = transition(state, action, session_id, observed)
            connection.execute("INSERT INTO pet_swap VALUES (1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                               (json.dumps(asdict(result)),))
        return result


def transition(state: PetSwap | None, action: str, session_id: str, observed: str) -> PetSwap:
    if action == "prepare":
        return prepare_swap(state, session_id, observed)
    if state is None:
        raise DoroError("No original official pet selection is saved")
    actions: dict[str, Callable[[], PetSwap]] = {
        "active": lambda: activate_swap(state, session_id, observed),
        "release": lambda: release_swap(state, session_id),
        "restored": lambda: finish_restore(state, observed),
    }
    if action not in actions:
        raise DoroError("Unknown local pet swap action")
    return actions[action]()
