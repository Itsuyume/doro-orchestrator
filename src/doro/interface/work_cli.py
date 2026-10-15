from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

from doro.application.work_bridge import WorkBridge
from doro.application.status import status_view
from doro.domain.models import Config, DoroError, Session
from doro.infrastructure.diagnostics import probe
from doro.infrastructure.providers import CliRunner
from doro.infrastructure.storage import LocalStore
from doro.interface.input import load_task, read_bounded


def add_work_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    work = commands.add_parser("work", help="Keep the current GPT Work chat as main worker")
    actions = work.add_subparsers(dest="work_action", required=True)
    start = actions.add_parser("start", help="Store a public Work draft; no model call")
    start.add_argument("--task", type=Path, required=True)
    start.add_argument("--draft", type=Path, required=True)
    for name in ("review", "reply", "finish", "status", "checkpoint", "decide"):
        action = actions.add_parser(name)
        action.add_argument("session_id")
        if name == "review":
            action.add_argument("--send", action="store_true")
        if name in ("reply", "finish"):
            action.add_argument("--text", type=Path, required=True)
        if name == "checkpoint":
            action.add_argument("--kind", choices=("start", "branch", "apply"), required=True)
            action.add_argument("--summary", type=Path, required=True)
        if name == "decide":
            action.add_argument("--checkpoint", required=True)
            action.add_argument("--decision", choices=("approve", "reject"), required=True)


def check_claude(config: Config) -> None:
    with tempfile.TemporaryDirectory(prefix="doro-work-auth-") as tmp:
        state = probe(config, "claude", Path(tmp))
    if state.get("authenticated") is not True:
        raise DoroError("Claude subscription authentication is not ready")


def execute_work(args: argparse.Namespace, config: Config, bridge: WorkBridge, store: LocalStore) -> Session:
    if args.work_action == "start":
        return bridge.start(load_task(config, args.task),
                            read_bounded(args.draft, config.limits.max_response_chars))
    if args.work_action == "review":
        if not args.send:
            raise DoroError("Work review requires --send; no external call was made")
        return bridge.review(args.session_id)
    if args.work_action in ("reply", "finish"):
        text = read_bounded(args.text, config.limits.max_response_chars)
        writer = bridge.reply if args.work_action == "reply" else bridge.finish
        return writer(args.session_id, text)
    if args.work_action == "checkpoint":
        return bridge.checkpoint(args.session_id, args.kind,
                                 read_bounded(args.summary, config.limits.max_response_chars))
    if args.work_action == "decide":
        return bridge.decide(args.session_id, args.checkpoint, args.decision)
    return store.load(args.session_id)


def run_work(args: argparse.Namespace, config: Config, root: Path) -> dict[str, object]:
    store = LocalStore(root / ".doro")
    bridge = WorkBridge(config, store, CliRunner(config),
                        lambda text: print(text, file=sys.stderr, flush=True), lambda: check_claude(config))
    return status_view(config, execute_work(args, config, bridge, store))
