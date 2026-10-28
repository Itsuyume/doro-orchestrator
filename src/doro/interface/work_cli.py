from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

from doro.application.work_bridge import WorkBridge
from doro.application.status import status_view
from doro.domain.models import Config, DoroError, OwnerRoute, Session
from doro.infrastructure.diagnostics import probe
from doro.infrastructure.model_settings import ModelSettings, SelectedAdvisorRunner
from doro.infrastructure.window_policy import collaboration_guard
from doro.infrastructure.storage import LocalStore, validate_owner
from doro.interface.input import load_task, read_bounded


def add_work_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    work = commands.add_parser("work", help="Keep the current GPT Work chat as main worker")
    actions = work.add_subparsers(dest="work_action", required=True)
    start = actions.add_parser("start", help="Store a public Work draft; no model call")
    start.add_argument("--task", type=Path, required=True)
    start.add_argument("--draft", type=Path, required=True)
    start.add_argument("--owner-thread", default="")
    start.add_argument("--label", default="도로 협업")
    start.add_argument("--scope", type=Path)
    start.add_argument("--brief", type=Path, help="Short approval scope, at most 280 characters")
    limits = start.add_mutually_exclusive_group()
    limits.add_argument("--bounded", action="store_true", help="Use configured interaction/cost ceilings (default)")
    limits.add_argument("--until-quota", action="store_true", help="Explicit override of cumulative local budgets")
    for name in ("review", "reply", "finish", "status", "checkpoint", "decide", "bind", "cancel", "retry", "limits"):
        action = actions.add_parser(name)
        action.add_argument("session_id")
        if name == "review":
            action.add_argument("--send", action="store_true")
            action.add_argument("--provider", choices=("claude", "agy"), default="claude")
        if name in ("reply", "finish"):
            action.add_argument("--text", type=Path, required=True)
        if name == "checkpoint":
            action.add_argument("--kind", choices=("start", "branch", "apply"), required=True)
            action.add_argument("--summary", type=Path, required=True)
            action.add_argument("--brief", type=Path, help="Human-readable decision/scope brief, at most 280 characters")
        if name == "decide":
            action.add_argument("--checkpoint", required=True)
            action.add_argument("--decision", choices=("approve", "reject"), required=True)
        if name == "bind":
            action.add_argument("--owner-thread", required=True)
            action.add_argument("--label", default="도로 협업")
        if name == "retry":
            action.add_argument("--instructions", type=Path, required=True)
            action.add_argument("--task", type=Path, help="Explicitly replace the public retry packet; earlier exact inputs are preserved")
            action.add_argument("--until-quota", action="store_true", help="Explicit human override of cumulative local call/cost/time budgets")
        if name == "limits":
            action.add_argument("--until-quota", action="store_true", required=True,
                                help="Remove existing Work interaction ceilings; no call or status reset")


def check_claude(config: Config) -> None:
    with tempfile.TemporaryDirectory(prefix="doro-work-auth-") as tmp:
        state = probe(config, "claude", Path(tmp))
    if state.get("authenticated") is not True:
        raise DoroError("Claude subscription authentication is not ready")


def start_work(args: argparse.Namespace, config: Config, bridge: WorkBridge, store: LocalStore) -> Session:
    if args.owner_thread:
        validate_owner(args.owner_thread, args.label)
    session = bridge.start(load_task(config, args.task),
                           read_bounded(args.draft, config.limits.max_response_chars),
                           read_bounded(args.scope, 6000) if args.scope else "", until_quota=args.until_quota,
                           brief=read_bounded(args.brief, 280) if args.brief else "")
    if args.owner_thread:
        store.bind(OwnerRoute(session.id, args.owner_thread, args.label))
    return session


def execute_work(args: argparse.Namespace, config: Config, bridge: WorkBridge, store: LocalStore) -> Session:
    if args.work_action == "start":
        return start_work(args, config, bridge, store)
    if args.work_action == "review":
        if not args.send:
            raise DoroError("Work review requires --send; no external call was made")
        return bridge.review(args.session_id, args.provider)
    if args.work_action in ("reply", "finish"):
        text = read_bounded(args.text, config.limits.max_response_chars)
        writer = bridge.reply if args.work_action == "reply" else bridge.finish
        return writer(args.session_id, text)
    if args.work_action == "checkpoint":
        return bridge.checkpoint(args.session_id, args.kind,
                                 read_bounded(args.summary, config.limits.max_response_chars),
                                 read_bounded(args.brief, 280) if args.brief else "")
    if args.work_action == "decide":
        return bridge.decide(args.session_id, args.checkpoint, args.decision)
    local_actions = {"cancel": bridge.cancel, "limits": bridge.lift_limits}
    if args.work_action in local_actions:
        return local_actions[args.work_action](args.session_id)
    if args.work_action == "retry":
        return bridge.retry(args.session_id, read_bounded(args.instructions, 2000), args.until_quota,
                            load_task(config, args.task) if args.task else None)
    if args.work_action == "bind":
        store.bind(OwnerRoute(args.session_id, args.owner_thread, args.label))
    return store.load(args.session_id)


def run_work(args: argparse.Namespace, config: Config, root: Path) -> dict[str, object]:
    store = LocalStore(root / ".doro")
    settings = ModelSettings(store)
    selected = getattr(args, "session_id", "*")
    config = settings.work_config(config, selected)
    guard = collaboration_guard(store.root) if args.work_action == "review" else None
    runner = SelectedAdvisorRunner(config, settings, selected, guard)
    bridge = WorkBridge(config, store, runner,
                        lambda text: print(text, file=sys.stderr, flush=True), lambda: check_claude(config))
    return status_view(config, execute_work(args, config, bridge, store))
