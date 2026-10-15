from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from doro.application.approval_relay import ApprovalRelay, relay_message
from doro.application.work_bridge import WorkBridge
from doro.domain.checkpoints import decide_checkpoint
from doro.domain.models import ApprovalReceipt, DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class ApprovalRelayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "orchestrator.toml")
        self.task = parse_task({**public_task(), "allowed_providers": ["claude"]})

    def test_only_explicitly_bound_pending_sessions_are_listed_without_body(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            session = WorkBridge(self.config, store, runner, lambda _: None).start(self.task, "PRIVATE_DRAFT")
            relay = ApprovalRelay(self.config, store)
            self.assertEqual(relay.pending(), [])
            owner = str(uuid4())
            store.bind(OwnerRoute(session.id, owner, "테스트 협업"))
            pending = relay.pending()
            self.assertEqual((pending[0]["session_id"], pending[0]["owner_thread_id"]), (session.id, owner))
            self.assertNotIn("PRIVATE_DRAFT", str(pending))
            self.assertEqual(runner.prompts, [])

    def test_human_reply_records_decision_and_outbox_without_model_or_automatic_send(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            session = WorkBridge(self.config, store, runner, lambda _: None).start(self.task, "Public draft")
            owner = str(uuid4())
            store.bind(OwnerRoute(session.id, owner, "테스트"))
            relay = ApprovalRelay(self.config, store)
            for checkpoint, answer in [(str(uuid4()), "승인"), (session.checkpoints[-1].id, "")]:
                with self.assertRaises(DoroError):
                    relay.respond(session.id, checkpoint, "approve", answer)
            receipt = relay.respond(session.id, session.checkpoints[-1].id, "approve", "이 범위로 승인해")
            self.assertEqual(receipt.owner_thread_id, owner)
            self.assertEqual(store.load(session.id).status, "awaiting_claude")
            self.assertEqual(relay.pending(), [])
            self.assertEqual(store.outbox(), (receipt,))
            self.assertIn("이 범위로 승인해", relay_message(receipt))
            self.assertEqual(runner.prompts, [])
            self.assertEqual(store.load(session.id).calls, {})
            with self.assertRaises(DoroError):
                relay.respond(session.id, session.checkpoints[-1].id, "approve", "또 승인")
            store.acknowledge(receipt.id)
            self.assertEqual(store.outbox(), ())
            self.assertTrue(store.receipt(receipt.id).delivered)

    def test_multiple_pending_sessions_require_explicit_identity_and_owner_cannot_be_rebound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, ExternalRunner(), lambda _: None)
            first, second = bridge.start(self.task, "First"), bridge.start(self.task, "Second")
            owner = str(uuid4())
            for session in (first, second):
                store.bind(OwnerRoute(session.id, owner, "협업"))
            with self.assertRaises(DoroError):
                store.bind(OwnerRoute(first.id, str(uuid4()), "다른 대화"))
            relay = ApprovalRelay(self.config, store)
            self.assertEqual(len(relay.pending()), 2)
            relay.respond(second.id, second.checkpoints[-1].id, "reject", "보류")
            self.assertEqual(store.load(second.id).status, "awaiting_direction")
            self.assertEqual(relay.pending()[0]["session_id"], first.id)

    def test_decision_and_receipt_are_one_transaction_when_storage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, ExternalRunner(), lambda _: None)
            first, second = bridge.start(self.task, "First"), bridge.start(self.task, "Second")
            owner = str(uuid4())
            for session in (first, second):
                store.bind(OwnerRoute(session.id, owner, "테스트"))
            relay = ApprovalRelay(self.config, store)
            receipt = relay.respond(first.id, first.checkpoints[-1].id, "approve", "승인")
            pending = store.load(second.id)
            decide_checkpoint(pending, pending.checkpoints[-1].id, "approve")
            duplicate = ApprovalReceipt(receipt.id, second.id, second.checkpoints[-1].id, owner, "approve", "승인")
            with self.assertRaises(sqlite3.IntegrityError):
                store.record_decision(pending, duplicate)
            self.assertEqual(store.load(second.id).status, "awaiting_approval")
            self.assertEqual(len(store.outbox()), 1)

    def test_closed_local_control_trial_cannot_launch_a_model_or_reopen_approval(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(self.config, store, runner, lambda _: None)
            session = bridge.start(self.task, "Local control test", "Only test native reply routing; no external model calls")
            store.bind(OwnerRoute(session.id, str(uuid4()), "로컬 시험"))
            relay = ApprovalRelay(self.config, store)
            relay.respond(session.id, session.checkpoints[-1].id, "approve", "로컬 시험 승인")
            bridge.cancel(session.id)
            for action in (lambda: bridge.review(session.id),
                           lambda: bridge.checkpoint(session.id, "branch", "Reopen")):
                with self.assertRaises(DoroError):
                    action()
            self.assertEqual(runner.prompts, [])
            self.assertEqual(store.load(session.id).calls, {})
