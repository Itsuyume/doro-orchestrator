from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from doro.domain.models import DoroError
from doro.domain.validation import keys, mapping, string
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore, private_directory, session_key


@dataclass(frozen=True)
class ViewerReceipt:
    path: Path
    request_id: str
    display: str
    intent: str = "open"


def window_target(store: LocalStore, explicit: str | None = None) -> tuple[str, bool]:
    routes = store.routes()
    if not routes:
        raise DoroError("No registered Work exists yet; start collaboration in its project first")
    registered = {route.session_id for route in routes}
    if explicit is not None:
        if session_key(explicit) not in registered:
            raise DoroError("The selected collaboration has no registered owner")
        return explicit, False
    # The seed only loads the task list. It never authorizes a project or a model call.
    return routes[-1].session_id, True


def write_request(store: LocalStore, session_id: str, display: str, *, show_tasks: bool = False,
                  intent: str = "open") -> ViewerReceipt:
    session_key(session_id)
    if display not in {"integrated", "panel", "hidden", "stop"}:
        raise DoroError("Unknown local viewer display mode")
    if intent not in {"open", "minimize", "hide"}:
        raise DoroError("Unknown local window action")
    directory = store.root / "native"
    private_directory(directory)
    inputs = LocalInputStore(store)
    tokens = {route.session_id: inputs.register_ui(route.session_id) for route in store.routes()}
    packet = {"version": 1, "request_id": str(uuid4()), "session_id": session_id,
              "display": display, "tokens": tokens, "show_tasks": show_tasks, "intent": intent}
    path = directory / "viewer-request.json"
    if path.is_symlink():
        raise DoroError("Viewer request symlinks are not allowed")
    temporary = directory / (str(uuid4()) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(packet, output)
    os.replace(temporary, path)
    return ViewerReceipt(path, str(packet["request_id"]), display, intent)


def acknowledged(path: Path, receipt: ViewerReceipt) -> bool:
    if path.is_symlink():
        raise DoroError("Viewer acknowledgement symlinks are not allowed")
    if not path.is_file():
        return False
    if path.stat().st_size > 2000:
        raise DoroError("Viewer acknowledgement is too large")
    packet = mapping(json.loads(path.read_text()), "viewer acknowledgement")
    keys(packet, {"request_id", "display"} | ({"intent"} if "intent" in packet else set()), "viewer acknowledgement")
    if string(packet["request_id"], "request ID") != receipt.request_id:
        return False
    if string(packet["display"], "display") != receipt.display:
        raise DoroError("The viewer acknowledged a different display mode")
    if packet.get("intent", "open") != receipt.intent:
        raise DoroError("The viewer did not confirm the requested window action")
    return True


def wait_for_ack(receipt: ViewerReceipt, timeout: float = 4) -> None:
    expected = receipt.request_id
    path = receipt.path.parent / "viewer-ack.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = mapping(json.loads(receipt.path.read_text()), "viewer request")
        if current.get("request_id") != expected:
            raise DoroError("A newer viewer request superseded this transition")
        if acknowledged(path, receipt):
            return
        time.sleep(0.05)
    raise DoroError("The existing viewer did not confirm the window action; no second viewer was started")
