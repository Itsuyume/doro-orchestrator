from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.serde import decode_session
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner, new_session
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class WorkBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "orchestrator.toml")
        self.task = parse_task({**public_task(), "allowed_providers": ["claude"]})

    def test_create_and_status_do_not_call_models(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            bridge = WorkBridge(self.config, LocalStore(Path(tmp)), runner, lambda _: None)
            session = bridge.start(self.task, "Public draft from this Work chat")
            self.assertEqual(session.mode, "work")
            self.assertEqual(session.participants, ("work", "claude"))
            self.assertEqual(session.turns[0].provider, "work")
            self.assertEqual(session.calls, {})
            self.assertEqual(runner.prompts, [])

    def test_work_claude_work_claude_work_roundtrip_uses_no_codex_cli(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, runner, lambda _: None)
            session = bridge.start(self.task, "WORK_DRAFT_public")
            reviewed = bridge.review(session.id)
            self.assertEqual(reviewed.status, "awaiting_work")
            self.assertIn("WORK_DRAFT_public", runner.prompts[0][1])
            bridge.reply(session.id, "WORK_REBUTTAL_public")
            bridge.review(session.id)
            self.assertIn("WORK_REBUTTAL_public", runner.prompts[1][1])
            self.assertIn("claude public reply 1", runner.prompts[1][1])
            finished = bridge.finish(session.id, "WORK_FINAL_public")
            self.assertEqual([t.provider for t in finished.turns],
                             ["work", "claude", "work", "claude", "work"])
            self.assertEqual(finished.calls, {"claude": 2})
            self.assertEqual(finished.turns[-1].phase, "final")
            self.assertEqual(finished.status, "completed")
            self.assertEqual([name for name, _ in runner.prompts], ["claude", "claude"])

    def test_request_and_rebuttal_limits_are_enforced_before_extra_calls(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            bridge = WorkBridge(self.config, LocalStore(Path(tmp)), runner, lambda _: None)
            session = bridge.start(self.task, "Public draft")
            with self.assertRaises(DoroError):
                bridge.finish(session.id, "Premature final")
            bridge.review(session.id)
            with self.assertRaises(DoroError):
                bridge.review(session.id)
            bridge.reply(session.id, "Public rebuttal")
            bridge.review(session.id)
            with self.assertRaises(DoroError):
                bridge.reply(session.id, "Third review request")
            self.assertEqual(len(runner.prompts), 2)

    def test_private_draft_and_unapproved_provider_are_never_forwarded(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            bridge = WorkBridge(self.config, LocalStore(Path(tmp)), runner, lambda _: None)
            with self.assertRaises(DoroError):
                bridge.start(self.task, "api_key=privateCredential")
            with self.assertRaises(DoroError):
                bridge.start(parse_task(public_task()), "Public draft")
            self.assertEqual(runner.prompts, [])

    def test_failure_preserves_main_draft_and_counters_for_explicit_retry(self) -> None:
        runner = ExternalRunner(fail_once=True)
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, runner, lambda _: None)
            session = bridge.start(self.task, "Public Work draft")
            with self.assertRaises(DoroError):
                bridge.review(session.id)
            failed = store.load(session.id)
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.calls, {"claude": 1})
            self.assertEqual(len(failed.turns), 1)
            bridge.review(session.id)
            finished = bridge.finish(session.id, "Explicit early Work final")
            self.assertEqual(finished.calls, {"claude": 2})
            self.assertEqual(finished.claude_reserved_usd, 1.0)

    def test_old_cli_sessions_remain_readable_without_rewriting_history(self) -> None:
        original = asdict(new_session(self.config))
        original.pop("mode")
        decoded = decode_session(json.dumps(original))
        self.assertEqual(decoded.mode, "cli")
        self.assertEqual(decoded.participants, ("codex", "claude"))

    def test_agy_enabling_cannot_expand_work_bridge_participants(self) -> None:
        agy = replace(self.config.providers["agy"], enabled=True)
        config = replace(self.config, providers={**self.config.providers, "agy": agy})
        with tempfile.TemporaryDirectory() as tmp:
            bridge = WorkBridge(config, LocalStore(Path(tmp)), ExternalRunner(), lambda _: None)
            with self.assertRaisesRegex(DoroError, "AGY"):
                bridge.start(self.task, "Public draft")
