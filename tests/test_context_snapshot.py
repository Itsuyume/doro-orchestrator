import argparse
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore
from doro.interface.chat_cli import run_chat
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class ContextSnapshotTests(unittest.TestCase):
    def test_context_snapshot_reports_approval_without_transcript_or_model_side_effect(self) -> None:
        config = load_config(ROOT / "orchestrator.toml")
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = LocalStore(root / ".doro")
            bridge = WorkBridge(config, store, runner, lambda _: None)
            session = bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "UNSHARED_DRAFT")
            store.bind(OwnerRoute(session.id, str(uuid4()), "Local task"))
            args = argparse.Namespace(session_id=session.id, wake=False, post=False, set_model=False,
                                      contexts_json=True, json=False, text=False)
            before = asdict(store.load(session.id))
            result = run_chat(args, config, root)
            self.assertIsInstance(result, dict)
            self.assertNotIn("UNSHARED_DRAFT", str(result))
            self.assertEqual(result, {"version": 1, "contexts": [{"session_id": session.id, "label": "Local task",
                "status": "승인 대기", "needs_input": True, "event_count": 1, "queued_inputs": 0, "finished": False}],
                "model_calls": 0})
            self.assertEqual(asdict(store.load(session.id)), before)
            self.assertEqual(runner.prompts, [])

    def test_unicode_limit_uses_code_points_and_invalid_input_has_no_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            runner = ExternalRunner()
            bridge = WorkBridge(load_config(ROOT / "orchestrator.toml"), store, runner, lambda _: None)
            session = bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Draft")
            store.bind(OwnerRoute(session.id, str(uuid4()), "Input limit"))
            inputs = LocalInputStore(store)
            token = inputs.register_ui(session.id)
            checkpoint = session.checkpoints[-1].id
            note = inputs.post(session.id, "🇰🇷" * 1000, checkpoint, token, str(uuid4()))
            self.assertEqual(len(note.text), 2000)
            with self.assertRaises(DoroError):
                inputs.post(session.id, "🇰🇷" * 1001, checkpoint, token, str(uuid4()))
            self.assertEqual(len(inputs.inputs(session.id)), 1)
            self.assertEqual(runner.prompts, [])
