from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class WorkRetryTests(unittest.TestCase):
    def test_retry_override_is_per_session_preserves_attempts_and_changes_actual_prompt(self) -> None:
        original = load_config(ROOT / "orchestrator.toml")
        config = replace(original, limits=replace(original.limits, max_calls=1, daily_calls=1, max_tokens=1,
                                                  session_reported_usd=0.5),
                         providers={**original.providers, "claude": replace(original.providers["claude"], max_calls=1)})
        runner = ExternalRunner(fail_once=True)
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(config, store, runner, lambda _: None)
            session = bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Public draft",
                                   until_quota=False)
            bridge.decide(session.id, session.checkpoints[-1].id, "approve")
            with self.assertRaises(DoroError):
                bridge.review(session.id)
            bridge.retry(session.id, "Return a smaller public component", False)
            with self.assertRaisesRegex(DoroError, "call limit"):
                bridge.review(session.id)
            bridge.retry(session.id, "Return one compact public component only", True)
            result = bridge.review(session.id)
            self.assertEqual(result.calls, {"claude": 2})
            self.assertEqual(len(result.exchanges), 2)
            self.assertIn("one compact public component", runner.prompts[-1][1])
            self.assertTrue(store.load(session.id).retry_until_quota)
            self.assertEqual(result.status, "awaiting_work")
            self.assertFalse(bridge.start(session.task, "Bounded draft", until_quota=False).retry_until_quota)

    def test_retry_preparation_cannot_bypass_approval_or_accept_sensitive_instructions(self) -> None:
        config = load_config(ROOT / "orchestrator.toml")
        runner = ExternalRunner(fail_once=True)
        with tempfile.TemporaryDirectory() as tmp:
            bridge = WorkBridge(config, LocalStore(Path(tmp)), runner, lambda _: None)
            session = bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Draft")
            with self.assertRaises(DoroError):
                bridge.retry(session.id, "Retry", True)
            bridge.decide(session.id, session.checkpoints[-1].id, "approve")
            with self.assertRaises(DoroError):
                bridge.review(session.id)
            for text in ("", "password=not-public"):
                with self.assertRaises(DoroError):
                    bridge.retry(session.id, text, True)
            self.assertEqual(len(runner.prompts), 1)
