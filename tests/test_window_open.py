import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.viewer_state import window_target, write_request
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class WindowOpenTests(unittest.TestCase):
    def test_empty_registry_refuses_to_invent_a_work_or_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            with self.assertRaisesRegex(DoroError, "No registered Work"):
                window_target(store)
            self.assertEqual(store.routes(), ())

    def test_open_shows_task_list_and_explicit_selection_is_registered_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            runner = ExternalRunner()
            bridge = WorkBridge(load_config(ROOT / "orchestrator.toml"), store, runner, lambda _: None)
            task = parse_task({**public_task(), "allowed_providers": ["claude"]})
            sessions = [bridge.start(task, "Draft A"), bridge.start(task, "Draft B")]
            for session in sessions:
                store.bind(OwnerRoute(session.id, str(uuid4()), "Registered task"))
            selected, tasks = window_target(store)
            self.assertEqual(selected, sessions[-1].id, "The task list must not seed an obsolete first demo")
            self.assertTrue(tasks, "Opening from the pet must let the human choose the target")
            receipt = write_request(store, selected, "panel", show_tasks=tasks)
            self.assertTrue(json.loads(receipt.path.read_text())["show_tasks"])
            self.assertEqual(receipt.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(window_target(store, sessions[1].id), (sessions[1].id, False))
            for invalid in ("", "../other", str(uuid4())):
                with self.assertRaises(DoroError):
                    window_target(store, invalid)
            self.assertEqual(runner.prompts, [])
            self.assertTrue(all(store.load(session.id).status == "awaiting_approval" for session in sessions))
