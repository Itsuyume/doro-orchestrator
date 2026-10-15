from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import time

from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.delivery_store import DeliveryOutbox
from doro.domain.models import DoroError
from doro.interface.input import read_bounded


def add_input_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    inputs = commands.add_parser("inputs", help="Read human native-chat messages without model calls or automatic approvals")
    actions = inputs.add_subparsers(dest="input_action", required=True)
    pending = actions.add_parser("pending")
    pending.add_argument("session_id")
    wait = actions.add_parser("wait")
    wait.add_argument("session_id")
    wait.add_argument("--timeout", type=float, default=55)
    ack = actions.add_parser("ack")
    ack.add_argument("note_id")
    ack.add_argument("--response", type=Path, help="Actual current Work reply; displayed locally, never auto-forwarded")
    get = actions.add_parser("get")
    get.add_argument("note_id")
    for action in (pending, wait, ack, get):
        action.add_argument("--owner-thread", required=True)


def run_inputs(args: argparse.Namespace, root: Path) -> object:
    store = LocalInputStore(LocalStore(root / ".doro"))
    if args.input_action == "wait":
        return wait_inputs(store, args.session_id, args.owner_thread, args.timeout)
    if args.input_action == "pending":
        return [asdict(note) for note in store.pending(args.session_id, args.owner_thread)]
    if args.input_action == "get":
        note = store.get(args.note_id)
        routes = {route.session_id: route.thread_id for route in store.sessions.routes()}
        if note.owner_thread_id != args.owner_thread or routes.get(note.session_id) != args.owner_thread:
            raise DoroError("Only the registered owning Work can receive this input")
        delivery = next((item for item in DeliveryOutbox(store.sessions).for_session(note.session_id) if item.input_id == note.id), None)
        return {"input": asdict(note), "delivery": asdict(delivery) if delivery else None}
    return asdict(store.acknowledge(args.note_id, args.owner_thread, read_bounded(args.response, 6000) if args.response else ""))


def wait_inputs(store: LocalInputStore, session_id: str, owner: str, timeout: float) -> object:
    if not 0 < timeout <= 55:
        raise ValueError("Native input wait must be between 0 and 55 seconds")
    deadline = time.monotonic() + timeout
    while True:
        pending = store.pending(session_id, owner)
        if pending or time.monotonic() >= deadline:
            return [asdict(note) for note in pending]
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
