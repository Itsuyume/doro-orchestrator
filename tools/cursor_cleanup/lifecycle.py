"""End screen-use cursor overlays without touching ChatGPT, Doro, or account settings."""
from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import ledger

CUA_TOOL = re.compile(r"cua_repl.*(?:js|js_reset)$")
IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")


def identifier(event: dict[str, object], name: str) -> str:
    value = event.get(name)
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Missing or invalid {name}; cleanup skipped")
    return value


def inspect(binary: Path, cleanup: bool = False) -> set[int]:
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("Cursor inspector is missing or is a symlink")
    result = subprocess.run([str(binary), "--cleanup" if cleanup else "--inspect"],
                            capture_output=True, text=True, timeout=2.5)
    if result.returncode:
        raise ValueError("Cursor inspector failed: " + result.stderr.strip())
    rows: object = json.loads(result.stdout)
    if not isinstance(rows, list):
        raise ValueError("Invalid cursor inspector result")
    ids: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid cursor inspector row")
        value: object = row.get("id")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("Invalid cursor window identifier")
        ids.add(value)
    return ids


def handle(event: dict[str, object], state: Path, snapshot: Callable[[], set[int]],
           cleanup: Callable[[], set[int]]) -> dict[str, str | int]:
    name = event.get("hook_event_name")
    tool = event.get("tool_name", "")
    if name in {"PreToolUse", "PostToolUse"} and (not isinstance(tool, str) or not CUA_TOOL.search(tool)):
        return {"status": "unrelated_tool"}
    session = identifier(event, "session_id")
    turn = None if name == "SessionEnd" else identifier(event, "turn_id")
    with ledger.connect(state) as connection:
        if name == "PreToolUse":
            assert turn is not None
            ledger.begin(connection, session, turn, snapshot())
            return {"status": "screen_use_registered"}
        finishing = name in {"Stop", "Interrupt", "SessionEnd", "ManualFinish"}
        finishing = finishing or (name == "PostToolUse" and isinstance(tool, str) and tool.endswith("js_reset"))
        if not finishing:
            return {"status": "screen_use_continues"}
        released = ledger.release(connection, session, turn)
        if name in {"Stop", "Interrupt"} and turn != "manual":
            released = ledger.release(connection, session, "manual") or released
        if not released:
            return {"status": "no_screen_use_in_this_turn"}
        if ledger.remaining(connection):
            return ledger.record(connection, "deferred_other_screen_use", 0, 0)
        before = snapshot()
        if before & ledger.protected(connection):
            return ledger.record(connection, "deferred_preexisting_cursors", len(before), len(before))
        after = cleanup() if before else before
        if after:
            raise ValueError("Cursor cleanup did not remove all overlays")
        return ledger.record(connection, "cleaned" if before else "already_clear", len(before), len(after))


def read_event() -> dict[str, object]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("begin", "finish", "status"))
    parser.add_argument("--session", default=os.environ.get("CODEX_THREAD_ID", ""))
    parser.add_argument("--turn", default="manual")
    args = parser.parse_args()
    if args.action:
        return {"hook_event_name": {"begin": "PreToolUse", "finish": "ManualFinish", "status": "Status"}[args.action],
                "session_id": args.session, "turn_id": args.turn, "tool_name": "mcp__cua_repl__js"}
    data: object = json.loads(sys.stdin.buffer.read(2_000_001))
    if not isinstance(data, dict):
        raise ValueError("Hook input must be an object")
    return {key: data[key] for key in ("hook_event_name", "session_id", "turn_id", "tool_name") if key in data}


def main() -> int:
    try:
        event = read_event()
        directory = Path(__file__).resolve().parent
        binary = directory / "inspect-cursors"
        state = Path.home() / ".codex/computer-use/cursor-cleanup/state.sqlite3"
        if event.get("hook_event_name") == "Status":
            print(json.dumps({"cursor_windows": len(inspect(binary))}))
            return 0
        result = handle(event, state, lambda: inspect(binary), lambda: inspect(binary, cleanup=True))
        warning = result["status"] == "deferred_preexisting_cursors"
        output = {"systemMessage": "기존 다른 화면 조작의 포인터가 있어 자동 정리를 미뤘도로."} if warning else {}
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"Cursor cleanup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
