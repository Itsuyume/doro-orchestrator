"""Cursor service is the only replaced external boundary; real SQLite coordinates turns."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools/cursor_cleanup"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("cursor_lifecycle", TOOLS / "lifecycle.py")
assert spec is not None and spec.loader is not None
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


class CursorCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state.sqlite3"
        self.visible: set[int] = set()
        self.cleanups = 0

    def cleanup(self) -> set[int]:
        self.cleanups += 1
        self.visible.clear()
        return set()

    def event(self, name: str, session: str = "A", turn: str = "one", tool: str = "mcp__cua_repl__js") -> dict[str, object]:
        return {"hook_event_name": name, "session_id": session, "turn_id": turn, "tool_name": tool}

    def run_event(self, name: str, session: str = "A", turn: str = "one", tool: str = "mcp__cua_repl__js") -> dict[str, str | int]:
        return lifecycle.handle(self.event(name, session, turn, tool), self.state, lambda: self.visible.copy(), self.cleanup)

    def test_unrelated_turn_and_duplicate_stop_do_not_touch_service(self) -> None:
        self.visible = {1}
        self.assertEqual(self.run_event("Stop")["status"], "no_screen_use_in_this_turn")
        self.assertEqual(self.run_event("PreToolUse", tool="Bash")["status"], "unrelated_tool")
        self.assertEqual(self.cleanups, 0)

    def test_stop_cleans_only_after_registered_screen_use(self) -> None:
        self.run_event("PreToolUse")
        self.visible = {1, 2, 3}
        self.assertEqual(self.run_event("Stop"), {"status": "cleaned", "before": 3, "after": 0})
        self.assertEqual(self.run_event("Stop")["status"], "no_screen_use_in_this_turn")
        self.assertEqual(self.cleanups, 1)

    def test_other_turns_and_other_chats_preserve_live_screen_use(self) -> None:
        self.run_event("PreToolUse")
        self.run_event("PreToolUse", turn="two")
        self.run_event("PreToolUse", session="B")
        self.visible = {4}
        self.assertEqual(self.run_event("Stop")["status"], "deferred_other_screen_use")
        self.assertEqual(self.run_event("Interrupt", turn="two")["status"], "deferred_other_screen_use")
        self.assertEqual(self.cleanups, 0)
        self.assertEqual(self.run_event("SessionEnd", session="B")["status"], "cleaned")

    def test_reset_finishes_screen_use_but_ordinary_ui_call_does_not(self) -> None:
        self.run_event("PreToolUse")
        self.visible = {4}
        self.assertEqual(self.run_event("PostToolUse")["status"], "screen_use_continues")
        self.assertEqual(self.run_event("PostToolUse", tool="mcp__cua_repl__js_reset")["status"], "cleaned")

    def test_preexisting_unknown_cursor_and_invalid_payload_never_signal(self) -> None:
        self.visible = {8}
        self.run_event("PreToolUse")
        self.visible.add(9)
        self.assertEqual(self.run_event("Stop")["status"], "deferred_preexisting_cursors")
        self.assertEqual(self.cleanups, 0)
        for event in ({}, {"hook_event_name": "Stop", "session_id": None}, self.event("Stop", turn="")):
            with self.assertRaises(ValueError):
                lifecycle.handle(event, self.state, lambda: self.visible.copy(), self.cleanup)
        self.assertEqual(self.cleanups, 0)

    def test_cleanup_failure_is_visible_and_transaction_is_retryable(self) -> None:
        self.run_event("PreToolUse")
        self.visible = {4}
        def failed() -> set[int]:
            raise OSError("Termination failed")
        with self.assertRaisesRegex(OSError, "Termination failed"):
            lifecycle.handle(self.event("Stop"), self.state, lambda: self.visible.copy(), failed)
        self.assertEqual(self.run_event("Stop")["status"], "cleaned")

    def test_stop_finishes_manual_registration_if_agent_did_not_explicitly_finish(self) -> None:
        self.run_event("PreToolUse", turn="manual")
        self.visible = {4}
        self.assertEqual(self.run_event("Stop", turn="actual-turn")["status"], "cleaned")
