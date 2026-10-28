from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError
from doro.domain.progress import progress
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class WorkLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = load_config(ROOT / "orchestrator.toml")
        self.config = replace(original, limits=replace(original.limits, daily_calls=1, max_calls=1,
                                                       max_tokens=1, session_reported_usd=0.5))
        self.store = LocalStore(Path(tmp.name))
        self.runner = ExternalRunner()
        self.bridge = WorkBridge(self.config, self.store, self.runner, lambda _: None)
        self.task = parse_task({**public_task(), "allowed_providers": ["claude"]})

    def test_default_work_stops_at_budget_before_a_second_external_call(self) -> None:
        config = replace(self.config, limits=replace(self.config.limits, max_tokens=100))
        bridge = WorkBridge(config, self.store, self.runner, lambda _: None)
        session = bridge.start(self.task, "Public scope before independent analysis")
        self.assertFalse(session.retry_until_quota)
        with self.assertRaises(DoroError):
            bridge.review(session.id)
        self.assertEqual(self.runner.prompts, [])
        bridge.decide(session.id, session.checkpoints[-1].id, "approve")
        bridge.review(session.id)
        bridge.reply(session.id, "GPT addresses the independent analysis")
        with self.assertRaisesRegex(DoroError, "Session call limit"):
            bridge.review(session.id)
        result = self.store.load(session.id)
        self.assertEqual((result.status, result.calls, len(result.exchanges)), ("failed", {"claude": 1}, 1))
        self.assertEqual(len(self.runner.prompts), 1)
        self.assertEqual(progress(config, result)["call_limit"], 1)

    def test_explicit_until_quota_preserves_the_legacy_override(self) -> None:
        session = self.bridge.start(self.task, "Public draft", until_quota=True)
        self.assertTrue(session.retry_until_quota)
        with self.assertRaises(DoroError):
            self.bridge.review(session.id)
        self.assertEqual(self.runner.prompts, [])
        self.bridge.decide(session.id, session.checkpoints[-1].id, "approve")
        for index in range(5):
            self.bridge.review(session.id)
            if index < 4:
                self.bridge.reply(session.id, f"Public focused improvement {index}")
        result = self.bridge.finish(session.id, "Work final judgment")
        self.assertEqual((result.status, result.calls, result.tokens_used), ("completed", {"claude": 5}, 100))
        self.assertEqual(len(result.exchanges), 5)
        self.assertEqual({name for name, _ in self.runner.prompts}, {"claude"})
        state = progress(self.config, result)
        self.assertIsNone(state["maximum_turns"])
        self.assertIsNone(state["claude_call_limit"])
        self.assertIsNone(state["call_limit"])

    def test_existing_limits_can_be_lifted_without_calling_or_reopening_completed_work(self) -> None:
        session = self.bridge.start(self.task, "Draft", until_quota=False)
        before = self.store.load(session.id)
        updated = self.bridge.lift_limits(session.id)
        self.assertTrue(updated.retry_until_quota)
        self.assertEqual((updated.status, updated.calls, updated.turns, updated.checkpoints),
                         (before.status, before.calls, before.turns, before.checkpoints))
        self.assertEqual(self.runner.prompts, [])
        self.bridge.decide(session.id, session.checkpoints[-1].id, "approve")
        self.bridge.review(session.id)
        self.bridge.finish(session.id, "Final")
        self.assertEqual(self.bridge.lift_limits(session.id).status, "completed")
        with self.assertRaises(DoroError):
            self.bridge.review(session.id)
        self.assertEqual(len(self.runner.prompts), 1)

    def test_unbounded_mode_still_stops_sensitive_external_output(self) -> None:
        self.runner.sensitive = True
        session = self.bridge.start(self.task, "Public draft", until_quota=True)
        self.bridge.decide(session.id, session.checkpoints[-1].id, "approve")
        with self.assertRaisesRegex(DoroError, "Sensitive"):
            self.bridge.review(session.id)
        result = self.store.load(session.id)
        self.assertEqual((result.status, len(result.turns), result.calls), ("failed", 1, {"claude": 1}))
        self.assertEqual(len(self.runner.prompts), 1)
