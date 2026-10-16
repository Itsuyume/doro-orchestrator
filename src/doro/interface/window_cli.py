from __future__ import annotations

import argparse
from pathlib import Path

from doro.infrastructure.native_chat import launch_viewer, native_sdk, viewer_app
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.viewer_state import window_target
from doro.infrastructure.window_policy import enable, required, viewer_identity
from doro.infrastructure.viewer_instance import runtime_directory


def add_window_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    window = commands.add_parser("window", help="Open the existing local task window; no model or new Work")
    actions = window.add_subparsers(dest="window_action", required=True)
    actions.add_parser("prepare", help="Build the local viewer cache without opening a window or Work")
    policy = actions.add_parser("policy", help="Read or enable the window lifetime gate for external calls")
    policy.add_argument("--require-running", action="store_true")
    for name in ("open", "minimize", "hide"):
        action = actions.add_parser(name, help="Local window control; no model, new Work, or message")
        if name == "open":
            action.add_argument("--session", help="Open one explicitly selected registered collaboration")


def run_window(args: argparse.Namespace, root: Path) -> object:
    if args.window_action == "policy":
        if args.require_running:
            enable(root / ".doro")
        return {"requires_running_window": required(root / ".doro"),
                "window_running": viewer_identity(root, runtime_directory()) is not None, "model_calls": 0}
    if args.window_action == "prepare":
        return {"app": str(viewer_app(root)), "sdk": native_sdk(root), "model_calls": 0}
    store = LocalStore(root / ".doro")
    selected, show_tasks = window_target(store, getattr(args, "session", None))
    display = "panel" if args.window_action == "open" else "hidden"
    return launch_viewer(root, selected, args.config, display,
                         show_tasks=show_tasks, intent=args.window_action)
