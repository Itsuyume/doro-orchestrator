from __future__ import annotations

import argparse
from pathlib import Path

from doro.infrastructure.native_chat import launch_viewer
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.viewer_state import window_target


def add_window_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    window = commands.add_parser("window", help="Open the existing local task window; no model or new Work")
    actions = window.add_subparsers(dest="window_action", required=True)
    opened = actions.add_parser("open", help="Show registered tasks without entering their Work chat")
    opened.add_argument("--session", help="Open one explicitly selected registered collaboration")


def run_window(args: argparse.Namespace, root: Path) -> object:
    store = LocalStore(root / ".doro")
    selected, show_tasks = window_target(store, args.session)
    return launch_viewer(root, selected, args.config, "panel", show_tasks=show_tasks)
