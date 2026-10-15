from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class CheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "orchestrator.toml")
        self.task = parse_task({**public_task(), "allowed_providers": ["claude"]})

    def test_start_waits_without_model_auth_or_budget_side_effects(self) -> None:
        runner = ExternalRunner()
        ready_calls: list[bool] = []
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, runner, lambda _: None,
                                lambda: ready_calls.append(True))
            session = bridge.start(self.task, "Public draft")
            with self.assertRaisesRegex(DoroError, "approval"):
                bridge.review(session.id)
            self.assertEqual(store.load(session.id).status, "awaiting_approval")
            self.assertEqual(store.load(session.id).calls, {})
            self.assertEqual(runner.prompts, [])
            self.assertEqual(ready_calls, [])
            checkpoint = session.checkpoints[-1]
            with self.assertRaises(DoroError):
                bridge.decide(session.id, str(uuid4()), "approve")
            bridge.decide(session.id, checkpoint.id, "approve")
            with self.assertRaises(DoroError):
                bridge.decide(session.id, checkpoint.id, "approve")
            bridge.review(session.id)
            self.assertEqual(ready_calls, [True])
            self.assertEqual(len(runner.prompts), 1)

    def test_branch_waits_and_rejection_prevents_calls_until_revised_approval(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, runner, lambda _: None)
            session = bridge.start(self.task, "Public draft")
            bridge.decide(session.id, session.checkpoints[-1].id, "approve")
            bridge.review(session.id)
            gate = bridge.checkpoint(session.id, "branch", "Choose the smaller public algorithm change")
            with self.assertRaises(DoroError):
                bridge.reply(session.id, "Bypass approval")
            bridge.decide(session.id, gate.checkpoints[-1].id, "reject")
            with self.assertRaises(DoroError):
                bridge.review(session.id)
            revised = bridge.checkpoint(session.id, "branch", "Keep the original algorithm")
            bridge.decide(session.id, revised.checkpoints[-1].id, "approve")
            bridge.finish(session.id, "Final public decision")
            self.assertEqual(len(runner.prompts), 1)
            self.assertEqual(store.load(session.id).calls, {"claude": 1})

    def test_apply_approval_is_separate_from_recording_the_final_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, ExternalRunner(), lambda _: None)
            session = bridge.start(self.task, "Public draft")
            bridge.decide(session.id, session.checkpoints[-1].id, "approve")
            bridge.review(session.id)
            bridge.finish(session.id, "Concrete final proposal; no project file applied")
            gate = bridge.checkpoint(session.id, "apply", "Apply the reviewed one-line public example")
            self.assertEqual(gate.status, "awaiting_approval")
            self.assertEqual(gate.checkpoints[-1].resume_status, "completed")
            bridge.decide(session.id, gate.checkpoints[-1].id, "approve")
            self.assertEqual(store.load(session.id).status, "completed")
            self.assertEqual(store.load(session.id).calls, {"claude": 1})

    def test_invalid_empty_sensitive_and_duplicate_checkpoints_leave_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, ExternalRunner(), lambda _: None)
            session = bridge.start(self.task, "Public draft")
            for kind, text in [("branch", ""), ("unknown", "Public"), ("apply", "api_key=private")]:
                with self.subTest(kind=kind), self.assertRaises(DoroError):
                    bridge.checkpoint(session.id, kind, text)
            with self.assertRaises(DoroError):
                bridge.checkpoint(session.id, "start", "Another pending approval")
            self.assertEqual(len(store.load(session.id).checkpoints), 1)
