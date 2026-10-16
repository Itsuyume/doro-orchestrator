from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.conversation import conversation
from doro.application.work_bridge import WorkBridge
from doro.application.work_delivery import WorkDispatcher, apply_deliveries
from doro.domain.models import DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.domain.work_delivery import DeliveryState, QueueFailure
from doro.infrastructure.config import load_config
from doro.infrastructure.delivery_store import DeliveryOutbox
from doro.infrastructure.delivery_timing import timing_for
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class ExternalQueue:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.failure: QueueFailure | None = None

    def enqueue(self, owner: str, message: str) -> str:
        self.sent.append((owner, message))
        if self.failure:
            raise self.failure
        return str(uuid4())


class WorkDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = load_config(ROOT / "orchestrator.toml")
        self.store = LocalStore(Path(tmp.name))
        self.runner = ExternalRunner()
        self.bridge = WorkBridge(self.config, self.store, self.runner, lambda _: None)
        self.session = self.bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Draft")
        self.owner = str(uuid4())
        self.store.bind(OwnerRoute(self.session.id, self.owner, "Work delivery"))
        self.inputs = LocalInputStore(self.store)
        self.outbox = DeliveryOutbox(self.store)
        self.token = self.inputs.register_ui(self.session.id)
        self.gate = self.session.checkpoints[-1].id
        self.queue = ExternalQueue()
        self.dispatcher = WorkDispatcher(self.outbox, self.queue)

    def post(self, decision: str = ""):
        return self.inputs.post(self.session.id, "Private UI input", self.gate, self.token, str(uuid4()), decision)

    def test_invalid_post_writes_neither_input_nor_outbox_and_never_sends(self) -> None:
        for text in ("", "\0", "x" * 2001):
            with self.assertRaises(DoroError):
                self.inputs.post(self.session.id, text, self.gate, self.token, str(uuid4()))
        self.assertEqual(self.inputs.inputs(self.session.id), ())
        self.assertEqual(self.outbox.for_session(self.session.id), ())
        self.assertEqual(self.queue.sent, [])

    def test_atomic_outbox_survives_reopen_and_duplicate_dispatch_sends_once(self) -> None:
        note = self.post("approve")
        reopened = LocalInputStore(LocalStore(self.store.root))
        self.assertEqual(reopened.get(note.id), note)
        self.assertEqual(self.outbox.for_session(self.session.id)[0].state, DeliveryState.PENDING)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.dispatcher.deliver(note), range(2)))
        self.assertEqual(len(self.queue.sent), 1)
        self.assertEqual(self.outbox.for_session(self.session.id)[0].state, DeliveryState.QUEUED)
        owner, message = self.queue.sent[0]
        self.assertEqual(owner, self.owner)
        self.assertNotIn(note.text, message)
        self.assertNotIn(self.token, message)
        self.assertIn(note.id, message)
        self.assertEqual(self.store.load(self.session.id).checkpoints[-1].decision, "pending")
        self.assertEqual(self.runner.prompts, [])

    def test_failure_is_visible_and_only_explicit_definite_retry_sends_again(self) -> None:
        note = self.post()
        self.queue.failure = QueueFailure("Unavailable", uncertain=False)
        failed = self.dispatcher.deliver(note)
        self.assertEqual(failed.state, DeliveryState.FAILED)
        self.assertEqual(self.dispatcher.deliver(note).state, DeliveryState.FAILED)
        self.assertEqual(len(self.queue.sent), 1)
        view = conversation(self.config, self.session, inputs=self.inputs.inputs(self.session.id))
        message = next(m for m in apply_deliveries(view, self.outbox.for_session(self.session.id)).messages if m.id == note.id)
        self.assertTrue(message.retryable)
        self.assertEqual(message.state, "Work 연결 실패")
        self.queue.failure = None
        self.assertEqual(self.dispatcher.deliver(note, retry=True).state, DeliveryState.QUEUED)
        self.assertEqual(len(self.queue.sent), 2)

    def test_uncertain_or_crashed_dispatch_is_never_automatically_resent(self) -> None:
        note = self.post()
        self.queue.failure = QueueFailure("Timeout", uncertain=True)
        self.assertEqual(self.dispatcher.deliver(note).state, DeliveryState.UNKNOWN)
        self.assertEqual(self.dispatcher.deliver(note, retry=True).state, DeliveryState.UNKNOWN)
        self.assertEqual(len(self.queue.sent), 1)
        other = self.post()
        self.outbox.claim(other)
        self.assertEqual(self.dispatcher.deliver(other).state, DeliveryState.DISPATCHING)
        self.assertEqual(len(self.queue.sent), 1)

    def test_owner_change_refuses_send_and_read_input_never_resends(self) -> None:
        note = self.post()
        with self.store.connect() as c:
            c.execute("UPDATE owners SET thread_id=? WHERE session_id=?", (str(uuid4()), self.session.id))
        with self.assertRaisesRegex(DoroError, "destination changed"):
            self.dispatcher.deliver(note)
        self.assertEqual(self.queue.sent, [])
        with self.store.connect() as c:
            c.execute("UPDATE owners SET thread_id=? WHERE session_id=?", (self.owner, self.session.id))
        self.inputs.acknowledge(note.id, self.owner, "Received")
        self.assertEqual(self.dispatcher.deliver(note).state, DeliveryState.RECEIVED)
        self.assertEqual(self.queue.sent, [])

    def test_changed_question_never_wakes_work_with_a_stale_decision(self) -> None:
        note = self.post("approve")
        self.bridge.decide(self.session.id, self.gate, "approve")
        result = self.dispatcher.deliver(note)
        self.assertEqual(result.state, DeliveryState.STALE)
        self.assertEqual(self.dispatcher.deliver(note, retry=True), result)
        self.assertEqual(self.queue.sent, [])
        self.assertEqual(self.runner.prompts, [])

    def test_first_receive_is_idempotent_and_distinct_from_final_response(self) -> None:
        note = self.post("approve")
        self.dispatcher.deliver(note)
        before = timing_for(self.store, note.id)
        with self.assertRaises(DoroError):
            self.inputs.receive(note.id, str(uuid4()))
        self.assertEqual(timing_for(self.store, note.id), before)
        with ThreadPoolExecutor(max_workers=2) as pool:
            received = list(pool.map(lambda _: self.inputs.receive(note.id, self.owner), range(2)))
        self.assertEqual(received, [note, note])
        first = timing_for(self.store, note.id)
        self.assertIsNotNone(first.saved_at)
        self.assertIsNotNone(first.queued_at)
        self.assertIsNotNone(first.received_at)
        self.assertIsNone(first.acknowledged_at)
        self.assertEqual(self.inputs.get(note.id).state, "queued")
        self.assertEqual(self.outbox.for_session(self.session.id)[0].state, DeliveryState.RECEIVED)
        self.assertEqual(self.store.load(self.session.id).checkpoints[-1].decision, "pending")
        self.assertEqual(self.inputs.pending(self.session.id, self.owner), (note,))
        self.assertEqual(timing_for(self.store, note.id), first)
        self.inputs.acknowledge(note.id, self.owner, "Actual response")
        final = timing_for(self.store, note.id)
        self.assertEqual(final.received_at, first.received_at)
        self.assertIsNotNone(final.acknowledged_at)
        self.assertEqual(self.inputs.get(note.id).response, "Actual response")
        self.assertEqual(len(self.queue.sent), 1)
        self.assertEqual(self.runner.prompts, [])

    def test_receive_racing_with_queue_receipt_preserves_both_once(self) -> None:
        note = self.post()
        self.outbox.claim(note)
        self.inputs.receive(note.id, self.owner)
        queue_id = str(uuid4())
        result = self.outbox.complete(note.id, DeliveryState.QUEUED, queue_id)
        self.assertEqual(result.state, DeliveryState.RECEIVED)
        self.assertEqual(result.queue_id, queue_id)
        self.assertEqual(self.dispatcher.deliver(note, retry=True), result)
        self.assertIsNotNone(timing_for(self.store, note.id).queued_at)
        self.assertEqual(self.queue.sent, [])

    def test_legacy_rows_keep_unknown_timestamps_and_owner_change_has_no_receipt(self) -> None:
        note = self.post()
        with self.store.connect() as connection:
            connection.execute("DROP TABLE delivery_timings")
        reopened = LocalInputStore(LocalStore(self.store.root))
        self.assertIsNone(timing_for(self.store, note.id).saved_at)
        reopened.receive(note.id, self.owner)
        self.assertIsNone(timing_for(self.store, note.id).saved_at)
        self.assertIsNotNone(timing_for(self.store, note.id).received_at)
        other = self.post()
        with self.store.connect() as connection:
            connection.execute("UPDATE owners SET thread_id=? WHERE session_id=?", (str(uuid4()), self.session.id))
        with self.assertRaises(DoroError):
            reopened.receive(other.id, self.owner)
        self.assertIsNone(timing_for(self.store, other.id).received_at)

    def test_already_answered_legacy_input_never_gets_an_invented_first_receipt_time(self) -> None:
        note = self.post()
        self.inputs.acknowledge(note.id, self.owner, "Old response")
        with self.store.connect() as connection:
            connection.execute("DROP TABLE delivery_timings")
        reopened = LocalInputStore(LocalStore(self.store.root))
        before = timing_for(self.store, note.id)
        self.assertEqual(reopened.receive(note.id, self.owner).state, "read")
        self.assertEqual(self.dispatcher.deliver(note).state, DeliveryState.RECEIVED)
        reopened.acknowledge(note.id, self.owner, "Old response")
        self.assertEqual(timing_for(self.store, note.id), before)
        self.assertIsNone(before.saved_at)
        self.assertIsNone(before.received_at)
        self.assertIsNone(before.acknowledged_at)
