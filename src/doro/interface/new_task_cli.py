from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time

from doro.application.work_delivery import WorkDispatcher
from doro.domain.models import Config, DoroError
from doro.domain.validation import keys, mapping, string
from doro.infrastructure.delivery_store import DeliveryOutbox
from doro.infrastructure.input_store import authorize_ui
from doro.infrastructure.new_task_chat import attach_chat, update_chat
from doro.infrastructure.new_task_store import NewTaskStore
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.work_queue import CodexQueue
from doro.interface.input import read_bounded


def add_new_task_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser("new-task", help="Create a separate GPT task from explicit native input")
    actions = parser.add_subparsers(dest="task_action", required=True)
    request = actions.add_parser("request")
    request.add_argument("--source-session", required=True)
    for name in ("status", "get", "wait", "claim", "created", "failed", "update"):
        action = actions.add_parser(name)
        action.add_argument("request_id")
        if name != "status":
            action.add_argument("--owner-thread", required=True)
        else:
            action.add_argument("--source-session")
        if name == "created":
            action.add_argument("--thread", required=True)
        if name == "failed":
            action.add_argument("--error", required=True)
            action.add_argument("--uncertain", action="store_true")
        if name == "update":
            action.add_argument("--text", type=Path, required=True)
            action.add_argument("--final", action="store_true")


def run_new_task(args: argparse.Namespace, config: Config, root: Path) -> object:
    store = NewTaskStore(LocalStore(root / ".doro"))
    if args.task_action == "request":
        return request_task(args, store, root)
    if args.task_action == "status":
        return read_status(store, args.request_id, args.source_session)
    request = store.get(args.request_id)
    if args.task_action == "wait":
        return wait_for_child(store, request.id, args.owner_thread)
    request, note = store.input(request.id, args.owner_thread)
    if args.task_action == "get":
        return {"request": asdict(request), "input": asdict(note)}
    if args.task_action == "claim":
        return {"claimed": store.claim(request.id, args.owner_thread), "request": asdict(store.get(request.id))}
    if args.task_action == "created":
        session = attach_chat(store, request.id, args.owner_thread, args.thread, config)
        return {"session_id": session, "request": asdict(store.get(request.id)), "model_calls": 0}
    if args.task_action == "failed":
        store.failed(request.id, args.owner_thread, args.error, args.uncertain)
        return asdict(store.get(request.id))
    session = update_chat(store, request.id, args.owner_thread, read_bounded(args.text, 6000), args.final)
    return {"session_id": session, "model_calls": 0}


def request_task(args: argparse.Namespace, store: NewTaskStore, root: Path) -> object:
    raw = sys.stdin.buffer.read(12_001)
    if len(raw) > 12_000:
        raise DoroError("New task input exceeds its transport bound")
    data = mapping(json.loads(raw), "new task input")
    keys(data, {"text", "client_id"}, "new task input")
    text, client_id = string(data["text"], "text"), string(data["client_id"], "client ID")
    token = os.environ.get("DORO_CHAT_CAPABILITY", "")
    request = store.begin(args.source_session, text, client_id, token)
    session = store.sessions.load(args.source_session)
    checkpoint = session.checkpoints[-1].id if session.status == "awaiting_approval" else ""
    note = store.inputs.post(args.source_session, text, checkpoint, token, client_id)
    delivery = WorkDispatcher(DeliveryOutbox(store.sessions), CodexQueue(root)).deliver(note, retry=True)
    return {"request": asdict(request), "delivery": asdict(delivery)}


def read_status(store: NewTaskStore, request_id: str, source: str | None) -> object:
    request = store.find(request_id)
    if source is None:
        if request is None:
            raise DoroError("The source UI connection is required to check an unsaved request")
        source = request.source_session
    with store.sessions.connect() as connection:
        authorize_ui(connection, source, os.environ.get("DORO_CHAT_CAPABILITY", ""))
        existing_input = connection.execute("SELECT id FROM user_inputs WHERE id=?", (request_id,)).fetchone()
    if request is None:
        return {"id": request_id, "state": "unknown" if existing_input else "not_submitted",
                "session_id": "", "thread_id": "", "token": "", "delivery": None,
                "error": "원본 입력은 있지만 생성 기록을 확인하지 못했도로. 자동 재전송하지 않도로." if existing_input else ""}
    if request.source_session != source:
        raise DoroError("Fresh-task status belongs to another UI connection")
    result = asdict(request)
    result["token"] = store.inputs.register_ui(request.session_id) if request.state == "created" else ""
    delivery = next((item for item in DeliveryOutbox(store.sessions).for_session(source)
                     if item.input_id == request.id), None)
    result["delivery"] = asdict(delivery) if delivery else None
    return result


def wait_for_child(store: NewTaskStore, request_id: str, owner: str) -> object:
    deadline = time.monotonic() + 10
    while True:
        request = store.get(request_id)
        if request.state == "created":
            _, note = store.input(request.id, owner)
            return {"request": asdict(request), "input": asdict(note)}
        if request.state not in {"pending", "creating"} or time.monotonic() >= deadline:
            raise DoroError("The broker has not confirmed the new GPT owner; no task was executed")
        time.sleep(0.05)
