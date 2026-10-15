from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys

from doro.application.conversation import context_summary, conversation, conversation_text
from doro.application.work_delivery import WorkDispatcher, apply_deliveries
from doro.domain.models import Config, DoroError
from doro.infrastructure.native_chat import launch_viewer
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.input_store import LocalInputStore, authorize_ui
from doro.infrastructure.delivery_store import DeliveryOutbox
from doro.infrastructure.work_queue import CodexQueue
from doro.infrastructure.model_settings import ModelSettings
from doro.domain.validation import keys, mapping, string


def add_chat_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    chat = commands.add_parser("chat", help="View one explicit session as native chat bubbles; no web or model call")
    chat.add_argument("session_id")
    chat.add_argument("--wake", action="store_true", help="Forward a validated native input to its existing Work")
    chat.add_argument("--display", choices=("integrated", "panel", "hidden", "stop"), default="panel",
                      help="One native viewer: integrated pet, transcript panel, or hidden; no model call")
    formats = chat.add_mutually_exclusive_group()
    formats.add_argument("--json", action="store_true", help="Read the typed local display snapshot")
    formats.add_argument("--text", action="store_true", help="Print the same actual conversation as text")
    formats.add_argument("--post", action="store_true", help="Record native UI input; --wake queues its existing Work")
    formats.add_argument("--retry-delivery", action="store_true", help="Retry a definitively failed native Work delivery")
    formats.add_argument("--set-model", action="store_true", help="Set the bound session's next-call model via native UI")


def run_chat(args: argparse.Namespace, config: Config, root: Path) -> object:
    store = LocalStore(root / ".doro")
    inputs = LocalInputStore(store)
    session = store.load(args.session_id)
    if not session.turns:
        raise DoroError("No saved conversation exists yet")
    labels = {route.session_id: route.label for route in store.routes()}
    if getattr(args, "wake", False) and not args.post:
        raise DoroError("--wake requires a validated --post input")
    if args.post:
        return post_input(inputs, session.id, root, getattr(args, "wake", False))
    if getattr(args, "retry_delivery", False):
        return retry_delivery(inputs, session.id, root)
    settings = ModelSettings(store)
    if args.set_model:
        data = mapping(json.loads(sys.stdin.buffer.read(2049)), "model selection")
        keys(data, {"model", "effort"}, "model selection")
        settings.save(string(data["model"], "model", empty=True), string(data["effort"], "effort"), session.id,
                      ui_token=os.environ.get("DORO_CHAT_CAPABILITY", ""))
        return {"saved": True, "applies": "next_review", "model_calls": 0}
    contexts = tuple(context_summary(store.load(sid), label, inputs.inputs(sid)) for sid, label in labels.items())
    view = conversation(config, session, labels.get(session.id, "도로 협업"), inputs.inputs(session.id), session.id in labels, contexts)
    view = replace(view, model_selection=settings.view(config, session.id))
    view = apply_deliveries(view, DeliveryOutbox(store).for_session(session.id))
    if args.json:
        return asdict(view)
    if args.text:
        return conversation_text(view)
    return launch_viewer(root, session.id, args.config, args.display)


def post_input(store: LocalInputStore, session_id: str, root: Path, wake: bool = False) -> object:
    raw = sys.stdin.buffer.read(12_001)
    if len(raw) > 12_000:
        raise DoroError("Native input transport exceeds its byte bound")
    data = mapping(json.loads(raw), "native input")
    keys(data, {"text", "checkpoint_id", "client_id", "decision"}, "native input")
    note = store.post(session_id, string(data["text"], "text"), string(data["checkpoint_id"], "checkpoint", empty=True),
                      os.environ.get("DORO_CHAT_CAPABILITY", ""), string(data["client_id"], "client_id"),
                      string(data["decision"], "decision", empty=True))
    result: dict[str, object] = {"id": note.id, "state": note.state, "model_calls": 0}
    if wake:
        delivery = WorkDispatcher(DeliveryOutbox(store.sessions), CodexQueue(root)).deliver(note)
        result["delivery"] = asdict(delivery)
        del result["model_calls"]
    return result


def retry_delivery(store: LocalInputStore, session_id: str, root: Path) -> object:
    data = mapping(json.loads(sys.stdin.buffer.read(1025)), "delivery retry")
    keys(data, {"input_id"}, "delivery retry")
    with store.sessions.connect() as connection:
        authorize_ui(connection, session_id, os.environ.get("DORO_CHAT_CAPABILITY", ""))
    note = store.get(string(data["input_id"], "input ID"))
    if note.session_id != session_id:
        raise DoroError("Input belongs to another collaboration; no delivery attempted")
    delivery = WorkDispatcher(DeliveryOutbox(store.sessions), CodexQueue(root)).deliver(note, retry=True)
    return {"id": note.id, "state": note.state, "delivery": asdict(delivery)}
