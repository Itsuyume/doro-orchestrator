from io import StringIO
from pathlib import Path
import tempfile
import unittest

from doro.domain.models import DoroError
from doro.infrastructure.input_notifications import HOOK_INPUT_LIMIT, hook_notice, hook_scope
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore

OWNER = "00000000-0000-0000-0000-000000000001"
ROOT_EVENT = {"hook_event_name": "PostToolUse", "session_id": OWNER, "turn_id": "opaque-turn"}


class InputNotificationIdleTests(unittest.TestCase):
    def test_idle_database_skips_unrelated_output_without_parsing_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LocalStore(Path(temporary) / ".doro")
            LocalInputStore(store)
            with store.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for payload in ("", "null", "not JSON", "x" * (HOOK_INPUT_LIMIT + 1)):
                    self.assertEqual(hook_notice(store.root, None, StringIO(payload)), {})
                self.assertEqual(connection.execute("SELECT count(*) FROM input_notifications").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT count(*) FROM delivery_timings").fetchone()[0], 0)

    def test_official_subagent_markers_are_denied_even_without_shell_thread_environment(self) -> None:
        for field in ("agent_id", "agent_type"):
            for value in (None, "", OWNER):
                self.assertIsNone(hook_scope({**ROOT_EVENT, field: value}, None))

    def test_root_identity_is_canonical_and_an_existing_shell_identity_must_agree(self) -> None:
        self.assertEqual(hook_scope(ROOT_EVENT, None), (OWNER, "opaque-turn"))
        self.assertEqual(hook_scope(ROOT_EVENT, OWNER), (OWNER, "opaque-turn"))
        self.assertIsNone(hook_scope(ROOT_EVENT, "00000000-0000-0000-0000-000000000002"))
        self.assertIsNone(hook_scope(ROOT_EVENT, ""))
        for value in (None, "", "not-a-uuid", OWNER.replace("0000", "000", 1)):
            with self.assertRaises(DoroError):
                hook_scope({**ROOT_EVENT, "session_id": value}, None)
