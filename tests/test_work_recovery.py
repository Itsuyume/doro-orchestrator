from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from doro.application.prompts import build_prompt
from doro.application.status import status_view
from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, PlannedTurn, Session, Task
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.serde import decode_session, encode_session
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class WorkRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = LocalStore(Path(temporary.name))
        self.original = load_config(ROOT / "orchestrator.toml")
        self.runner = ExternalRunner()
        self.task = parse_task({**public_task(), "allowed_providers": ["claude"]})
        self.old = WorkBridge(self.original, self.store, self.runner, lambda _: None)
        self.session = self.old.start(self.task, "ORIGINAL_PUBLIC_DRAFT")
        self.changed = replace(self.original, fingerprint="b" * 64,
                               roles={**self.original.roles, "claude": "Updated public advisor role"})
        self.bridge = WorkBridge(self.changed, self.store, self.runner, lambda _: None)
        self.gate = self.session.checkpoints[-1].id

    def state_hash(self) -> str:
        return str(status_view(self.changed, self.store.load(self.session.id))["session_sha256"])

    def recover(self, *, checkpoint_id: str | None = None, expected_state: str | None = None,
                expected_config: str | None = None, task: Task | None = None,
                draft: str = "EXACT_APPROVED_PUBLIC_REVISION",
                reason: str = "Human requested role recovery") -> Session:
        return self.bridge.recover(self.session.id, checkpoint_id or self.gate,
                                   self.state_hash() if expected_state is None else expected_state,
                                   self.changed.fingerprint if expected_config is None else expected_config,
                                   self.task if task is None else task, draft, reason)

    def test_recovery_preserves_originals_approval_and_counters_without_model_calls(self) -> None:
        before = deepcopy(self.store.load(self.session.id))
        recovered = self.recover()
        saved = self.store.load(self.session.id)
        self.assertEqual(saved.id, before.id)
        self.assertEqual(saved.turns[:-1], before.turns)
        self.assertEqual(saved.checkpoints, before.checkpoints)
        self.assertEqual((saved.calls, saved.seconds_used, saved.tokens_used, saved.status),
                         (before.calls, before.seconds_used, before.tokens_used, before.status))
        self.assertEqual(saved.config_fingerprint, self.changed.fingerprint)
        self.assertEqual(saved.recoveries[0].previous_fingerprint, self.original.fingerprint)
        self.assertEqual(saved.recoveries[0].previous_task, before.task)
        self.assertEqual(saved.recoveries[0].checkpoint_id, self.gate)
        self.assertEqual(saved.recoveries[0].turn_index, 1)
        self.assertEqual(decode_session(encode_session(recovered)), saved)
        self.assertEqual(self.runner.prompts, [])
        with self.assertRaisesRegex(DoroError, "approval"):
            self.bridge.review(saved.id)

    def test_only_current_approved_packet_is_sent_after_the_existing_gate_is_decided(self) -> None:
        task = replace(self.task, message="APPROVED_UPDATED_PUBLIC_TASK")
        recovered = self.recover(task=task)
        self.bridge.decide(recovered.id, self.gate, "approve")
        reviewed = self.bridge.review(recovered.id)
        prompt = self.runner.prompts[0][1]
        self.assertIn(task.message, prompt)
        self.assertIn("EXACT_APPROVED_PUBLIC_REVISION", prompt)
        self.assertNotIn("ORIGINAL_PUBLIC_DRAFT", prompt)
        self.assertIn("ORIGINAL_PUBLIC_DRAFT", self.store.export(reviewed).read_text())
        self.assertEqual(reviewed.calls, {"claude": 1})
        self.assertEqual(reviewed.checkpoints[0].id, self.gate)

    def test_stale_state_config_checkpoint_and_expanded_provider_fail_without_writes(self) -> None:
        for changes in ({"expected_state": "0" * 64}, {"expected_config": "0" * 64},
                        {"checkpoint_id": "stale"}, {"task": replace(self.task, allowed_providers=("claude", "agy"))}):
            with self.subTest(changes=changes):
                before = encode_session(self.store.load(self.session.id))
                with self.assertRaises(DoroError):
                    self.recover(**changes)
                self.assertEqual(encode_session(self.store.load(self.session.id)), before)
        self.assertEqual(self.runner.prompts, [])

    def test_empty_sensitive_and_oversized_draft_or_reason_are_rejected(self) -> None:
        for changes in ({"draft": ""}, {"draft": "password=private"},
                        {"draft": "x" * (self.changed.limits.max_response_chars + 1)},
                        {"reason": ""}, {"reason": "x" * 1001},
                        {"task": replace(self.task, classification="private")}):
            with self.subTest(changes=list(changes)):
                before = encode_session(self.store.load(self.session.id))
                with self.assertRaises(DoroError):
                    self.recover(**changes)
                self.assertEqual(encode_session(self.store.load(self.session.id)), before)
        self.assertEqual(self.runner.prompts, [])

    def test_duplicate_recovery_and_future_role_change_require_explicit_new_recovery(self) -> None:
        self.recover()
        with self.assertRaisesRegex(DoroError, "already matches"):
            self.recover()
        later = replace(self.changed, fingerprint="c" * 64)
        bridge = WorkBridge(later, self.store, self.runner, lambda _: None)
        with self.assertRaisesRegex(DoroError, "work recover"):
            bridge.decide(self.session.id, self.gate, "approve")
        self.assertEqual(self.runner.prompts, [])

    def test_concurrent_lock_and_changed_rounds_leave_history_untouched(self) -> None:
        before = encode_session(self.store.load(self.session.id))
        with self.store.lock(self.session.id), self.assertRaisesRegex(DoroError, "concurrent"):
            self.recover()
        changed = replace(self.changed, limits=replace(self.changed.limits, debate_rounds=1))
        self.bridge = WorkBridge(changed, self.store, self.runner, lambda _: None)
        with self.assertRaisesRegex(DoroError, "round"):
            self.recover(expected_config=changed.fingerprint)
        self.assertEqual(encode_session(self.store.load(self.session.id)), before)

    def test_running_completed_and_rejected_sessions_are_not_reopened(self) -> None:
        for status in ("running", "completed", "cancelled", "awaiting_direction"):
            with self.subTest(status=status):
                record = deepcopy(self.session)
                record.status = status
                self.store.save(record)
                with self.assertRaises(DoroError):
                    self.recover()
                self.assertEqual(self.store.load(record.id).status, status)

    def test_corrupt_revision_index_cannot_drop_history_or_reach_the_runner(self) -> None:
        record = self.recover()
        record.recoveries[0] = replace(record.recoveries[0], turn_index=999)
        self.store.save(record)
        with self.assertRaises(DoroError):
            self.bridge.decide(record.id, self.gate, "approve")
        with self.assertRaises(DoroError):
            build_prompt(record, PlannedTurn("claude", "review"), self.changed.roles["claude"], 24000)
        self.assertEqual(self.runner.prompts, [])
