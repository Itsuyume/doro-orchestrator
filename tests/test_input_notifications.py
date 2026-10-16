from concurrent.futures import ThreadPoolExecutor
import argparse
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.domain.work_delivery import DeliveryState, input_notice
from doro.infrastructure.config import load_config
from doro.infrastructure.delivery_store import DeliveryOutbox
from doro.infrastructure.delivery_timing import timing_for
from doro.infrastructure.input_notifications import HOOK_INPUT_LIMIT, NOTICE_LIMIT, hook_notice
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore
from doro.interface.input_cli import run_inputs
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class InputNotificationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = LocalStore(Path(tmp.name) / ".doro")
        self.runner = ExternalRunner()
        self.bridge = WorkBridge(load_config(ROOT / "orchestrator.toml"), self.store, self.runner, lambda _: None)
        self.session = self.bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Draft")
        self.owner, self.turn = str(uuid4()), str(uuid4())
        self.store.bind(OwnerRoute(self.session.id, self.owner, "Input notifications"))
        self.inputs = LocalInputStore(self.store)
        self.token = self.inputs.register_ui(self.session.id)
        self.outbox = DeliveryOutbox(self.store)

    def post(self, state: DeliveryState | None = DeliveryState.QUEUED):
        note = self.inputs.post(self.session.id, "Private local message", self.session.checkpoints[-1].id,
                                self.token, str(uuid4()))
        if state is not None:
            self.outbox.claim(note)
            if state != DeliveryState.DISPATCHING:
                self.outbox.complete(note.id, state, str(uuid4()) if state == DeliveryState.QUEUED else "")
        return note

    def event(self, **changes):
        return {"hook_event_name": "PostToolUse", "session_id": self.owner, "turn_id": self.turn,
                "tool_response": "Private tool output", **changes}

    def notify(self, **changes):
        return hook_notice(self.store.root, self.owner, StringIO(json.dumps(self.event(**changes))))

    def test_empty_null_malformed_oversized_or_wrong_owner_never_receives_or_sends(self) -> None:
        note = self.post()
        for payload in ("", "null", "[]", "{", "x" * (HOOK_INPUT_LIMIT + 1)):
            with self.assertRaises((DoroError, ValueError)):
                hook_notice(self.store.root, self.owner, StringIO(payload))
        for fields in ({"session_id": str(uuid4())}, {"agent_id": str(uuid4())},
                       {"agent_type": "worker"}, {"hook_event_name": "Stop"}):
            self.assertEqual(self.notify(**fields), {})
        self.assertEqual(hook_notice(self.store.root, None, StringIO(json.dumps(self.event()))), {})
        self.assertEqual(timing_for(self.store, note.id).notified_at, None)
        self.assertEqual(self.inputs.get(note.id).state, "queued")
        self.assertEqual(self.runner.prompts, [])

    def test_unregistered_or_missing_store_is_a_noop(self) -> None:
        missing = self.store.root / "absent"
        self.assertEqual(hook_notice(missing, self.owner, StringIO(json.dumps(self.event()))), {})
        self.assertFalse(missing.exists())
        with self.store.connect() as connection:
            connection.execute("DELETE FROM owners")
        self.assertEqual(self.notify(), {})
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM input_notifications").fetchone()[0], 0)
        self.assertEqual(hook_notice(self.store.root, str(uuid4()), StringIO("not JSON")), {})

    def test_idle_hook_does_not_take_a_write_lock_and_busy_claim_remains_retryable(self) -> None:
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.assertEqual(self.notify(), {})
        note = self.post()
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.OperationalError):
                self.notify()
        self.assertIsNone(timing_for(self.store, note.id).notified_at)
        self.assertTrue(self.notify())

    def test_hook_never_migrates_a_legacy_database(self) -> None:
        self.post()
        with self.store.connect() as connection:
            connection.execute("DROP TABLE input_notifications")
        self.assertEqual(self.notify(), {})
        with self.store.connect() as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='input_notifications'").fetchone())
        LocalInputStore(self.store)
        self.assertTrue(self.notify())

    def test_turn_identifier_is_opaque_but_bounded(self) -> None:
        self.post()
        for value in (None, "", "x" * 201, "turn\nnext"):
            with self.assertRaises((DoroError, ValueError)):
                self.notify(turn_id=value)
        self.assertTrue(self.notify(turn_id="turn/opaque-identifier"))

    def test_notice_has_only_identifiers_and_does_not_acknowledge_or_approve(self) -> None:
        note = self.post()
        result = self.notify()
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn(input_notice(note.id, note.session_id, self.owner), context)
        self.assertNotIn(note.text, context)
        self.assertNotIn("Private tool output", json.dumps(result))
        self.assertNotIn(self.token, context)
        self.assertNotIn("decision", result)
        self.assertEqual(self.inputs.get(note.id).state, "queued")
        self.assertIsNone(timing_for(self.store, note.id).received_at)
        self.assertIsNotNone(timing_for(self.store, note.id).notified_at)
        self.assertEqual(self.store.load(self.session.id).checkpoints[-1].decision, "pending")
        self.assertEqual(self.runner.prompts, [])

    def test_other_registered_work_input_is_not_exposed_or_marked_notified(self) -> None:
        other = self.bridge.start(self.session.task, "Other public draft")
        other_owner = str(uuid4())
        self.store.bind(OwnerRoute(other.id, other_owner, "Other Work"))
        other_token = self.inputs.register_ui(other.id)
        note = self.inputs.post(other.id, "Other private message", other.checkpoints[-1].id,
                                other_token, str(uuid4()))
        self.outbox.claim(note)
        self.outbox.complete(note.id, DeliveryState.QUEUED, str(uuid4()))
        self.assertEqual(self.notify(), {})
        self.assertIsNone(timing_for(self.store, note.id).notified_at)
        own = self.post()
        context = self.notify()["hookSpecificOutput"]["additionalContext"]
        self.assertIn(own.id, context)
        self.assertNotIn(note.id, context)
        self.assertIsNone(timing_for(self.store, note.id).notified_at)

    def test_concurrent_tool_boundaries_notify_once_per_turn_with_a_fixed_batch_bound(self) -> None:
        notes = [self.post() for _ in range(NOTICE_LIMIT + 2)]
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.notify(), range(3)))
        contexts = [r["hookSpecificOutput"]["additionalContext"] for r in results if r]
        self.assertEqual(len(contexts), 2)
        for context in contexts:
            self.assertLessEqual(context.count("DORO_INPUT "), NOTICE_LIMIT)
        for note in notes:
            self.assertEqual(sum(context.count(note.id) for context in contexts), 1)
        self.assertEqual(self.notify(), {})
        self.assertTrue(self.notify(turn_id=str(uuid4())))

    def test_active_delivery_notifies_before_queue_returns_and_late_queue_never_reexecutes(self) -> None:
        note = self.post(DeliveryState.DISPATCHING)
        self.assertTrue(self.notify())
        self.inputs.receive(note.id, self.owner)
        self.assertEqual(self.notify(turn_id=str(uuid4())), {})
        receipt = self.outbox.complete(note.id, DeliveryState.QUEUED, str(uuid4()))
        self.assertEqual(receipt.state, DeliveryState.RECEIVED)
        self.assertTrue(receipt.queue_id)
        self.assertEqual(self.inputs.get(note.id).state, "queued")
        self.inputs.acknowledge(note.id, self.owner, "Handled once")
        self.assertEqual(self.inputs.get(note.id).response, "Handled once")
        self.assertEqual(self.notify(turn_id=str(uuid4())), {})

    def test_saved_only_failed_and_changed_owner_never_notify_but_unknown_can_notify(self) -> None:
        self.post(None)
        self.post(DeliveryState.FAILED)
        self.assertEqual(self.notify(), {})
        uncertain = self.post(DeliveryState.UNKNOWN)
        self.assertIn(uncertain.id, self.notify()["hookSpecificOutput"]["additionalContext"])
        self.post()
        with self.store.connect() as connection:
            connection.execute("UPDATE owners SET thread_id=?", (str(uuid4()),))
        self.assertEqual(self.notify(turn_id=str(uuid4())), {})

    def test_cli_get_returns_the_original_message_and_records_receipt_before_final_ack(self) -> None:
        note = self.post()
        args = argparse.Namespace(input_action="get", note_id=note.id, owner_thread=self.owner)
        result = run_inputs(args, self.store.root.parent)
        self.assertEqual(result["input"]["text"], note.text)
        self.assertEqual(result["input"]["state"], "queued")
        self.assertEqual(result["input"]["response"], "")
        self.assertEqual(result["delivery"]["state"], "received")
        self.assertIsNotNone(result["timing"]["received_at"])
        self.assertIsNone(result["timing"]["acknowledged_at"])
        self.assertEqual(self.store.load(self.session.id).checkpoints[-1].decision, "pending")
        self.assertEqual(self.runner.prompts, [])
        self.inputs.acknowledge(note.id, self.owner, "Completed once")
        repeated = run_inputs(args, self.store.root.parent)
        self.assertEqual(repeated["input"]["state"], "read")
        self.assertEqual(repeated["input"]["response"], "Completed once")
        self.assertIsNotNone(repeated["timing"]["acknowledged_at"])
