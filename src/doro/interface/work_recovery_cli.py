from __future__ import annotations

import argparse
import os
from pathlib import Path

from doro.application.work_bridge import WorkBridge
from doro.domain.models import Config, DoroError, Session
from doro.infrastructure.storage import LocalStore
from doro.interface.input import load_task, read_bounded


def add_recovery_parser(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    action = actions.add_parser("recover", help="Explicit owner-bound recovery; no approval or model call")
    action.add_argument("session_id")
    for flag in ("owner-thread", "checkpoint", "expected-state", "expected-config", "task-sha256", "draft-sha256"):
        action.add_argument("--" + flag, required=True)
    for flag in ("task", "draft", "reason"):
        action.add_argument("--" + flag, type=Path, required=True)


def recover_work(args: argparse.Namespace, config: Config, bridge: WorkBridge, store: LocalStore) -> Session:
    owner = next((route for route in store.routes() if route.session_id == args.session_id), None)
    if owner is None or owner.thread_id != args.owner_thread or os.environ.get("CODEX_THREAD_ID") != owner.thread_id:
        raise DoroError("Configuration recovery must run in the immutable registered owner Work")
    task = load_task(config, args.task, args.task_sha256)
    draft = read_bounded(args.draft, config.limits.max_response_chars, args.draft_sha256)
    reason = read_bounded(args.reason, 1000)
    return bridge.recover(args.session_id, args.checkpoint, args.expected_state, args.expected_config,
                          task, draft, reason)
