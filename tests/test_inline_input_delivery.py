from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.work_bridge import WorkBridge
from doro.domain.models import OwnerRoute
from doro.domain.validation import parse_task
from doro.domain.work_delivery import DeliveryState, input_notice
from doro.infrastructure.config import load_config
from doro.infrastructure.delivery_store import DeliveryOutbox
from doro.infrastructure.delivery_timing import timing_for
from doro.infrastructure.input_notifications import hook_notice
from doro.infrastructure.input_queue_guard import guard_notice
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.new_task_store import NewTaskStore
from doro.infrastructure.storage import LocalStore
from test_input_context import body_records
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class InlineInputDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = LocalStore(Path(temporary.name) / ".doro")
        self.runner = ExternalRunner()
        self.bridge = WorkBridge(load_config(ROOT / "orchestrator.toml"), self.store, self.runner, lambda _: None)
        self.session = self.bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Draft")
        self.owner = str(uuid4())
        self.store.bind(OwnerRoute(self.session.id, self.owner, "Inline input"))
        self.inputs = LocalInputStore(self.store)
        self.token = self.inputs.register_ui(self.session.id)
        self.outbox = DeliveryOutbox(self.store)

    def post(self, text="채팅 원문", note_id=None, decision=""):
        note = self.inputs.post(self.session.id, text, self.session.checkpoints[-1].id,
                                self.token, note_id or str(uuid4()), decision)
        self.outbox.claim(note)
        self.outbox.complete(note.id, DeliveryState.QUEUED, str(uuid4()))
        return note

    def notify(self, turn=None, **changes):
        event = {"hook_event_name": "PostToolUse", "session_id": self.owner,
                 "turn_id": turn or str(uuid4()), "tool_response": "Unrelated tool data", **changes}
        return hook_notice(self.store.root, None, StringIO(json.dumps(event)))

    def guard(self, note, **changes):
        event = {"hook_event_name": "UserPromptSubmit", "session_id": self.owner,
                 "prompt": input_notice(note.id, note.session_id, note.owner_thread_id), **changes}
        return guard_notice(self.store.root, None, StringIO(json.dumps(event)))

    def test_active_body_reaches_context_without_get_or_false_receipt_and_ack_stops_queue_echo(self) -> None:
        note = self.post("즉시 전달할 채팅")
        context = self.notify()["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(body_records(context)[0]["input"]["text"], note.text)
        timing = timing_for(self.store, note.id)
        self.assertIsNotNone(timing.notified_at)
        self.assertIsNone(timing.received_at)
        self.assertIsNone(timing.acknowledged_at)
        self.assertEqual(self.inputs.get(note.id).state, "queued")
        self.assertNotIn("Unrelated tool data", context)
        self.assertNotIn(self.token, context)
        self.inputs.acknowledge(note.id, self.owner, "답변")
        self.assertEqual(self.guard(note), {"continue": False})
        self.assertEqual(self.notify(), {})
        self.assertEqual(self.inputs.get(note.id).response, "답변")
        self.assertEqual(self.bridge.store.load(self.session.id).checkpoints[-1].decision, "pending")
        self.assertEqual(self.runner.prompts, [])

    def test_idle_context_is_read_only_and_unanswered_input_survives(self) -> None:
        note = self.post()
        with self.store.connect() as connection:
            before = tuple(connection.iterdump())
            connection.execute("BEGIN IMMEDIATE")
            result = self.guard(note)
            self.assertEqual(tuple(connection.iterdump()), before)
        self.assertNotIn("continue", result)
        self.assertEqual(body_records(result["hookSpecificOutput"]["additionalContext"])[0]["input"]["id"], note.id)
        self.assertIsNone(timing_for(self.store, note.id).received_at)
        self.assertEqual(self.inputs.get(note.id).state, "queued")

    def test_only_exact_same_owner_root_events_can_expose_a_body(self) -> None:
        note = self.post("Local-only body")
        for changes in ({"session_id": str(uuid4())}, {"agent_id": None}, {"agent_type": ""}):
            self.assertEqual(self.notify(**changes), {})
            self.assertEqual(self.guard(note, **changes), {})
        with self.store.connect() as connection:
            connection.execute("UPDATE owners SET thread_id=?", (str(uuid4()),))
        self.assertEqual(self.notify(), {})
        self.assertEqual(self.guard(note), {})

    def test_native_decisions_and_new_task_requests_always_require_lookup(self) -> None:
        decision = self.post("승인 버튼 원문", decision="approve")
        tasks = NewTaskStore(self.store)
        request = tasks.begin(self.session.id, "새 작업 원문", str(uuid4()), self.token)
        note = self.post("새 작업 원문", request.id)
        for item in (decision, note):
            context = self.guard(item)["hookSpecificOutput"]["additionalContext"]
            self.assertEqual(body_records(context), [])
            self.assertNotIn(item.text, context)
            self.assertIn(input_notice(item.id, item.session_id, self.owner), context)
        active = self.notify()["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(body_records(active), [])
        self.assertEqual(self.bridge.store.load(self.session.id).checkpoints[-1].decision, "pending")

    def test_concurrent_hooks_emit_each_body_once_per_turn_and_preserve_the_next_turn(self) -> None:
        notes = [self.post(str(index)) for index in range(7)]
        turn = str(uuid4())
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.notify(turn), range(3)))
        records = [record for result in results if result
                   for record in body_records(result["hookSpecificOutput"]["additionalContext"])]
        self.assertCountEqual([record["input"]["id"] for record in records], [note.id for note in notes])
        self.assertEqual(self.notify(turn), {})
        self.assertTrue(self.notify())

    def test_corrupt_text_does_not_block_another_input_or_hide_the_error(self) -> None:
        bad, good = self.post("bad"), self.post("정상 입력")
        with self.store.connect() as connection:
            connection.execute("UPDATE user_inputs SET text=? WHERE id=?", ("x" * 2001, bad.id))
        context = self.notify()["hookSpecificOutput"]["additionalContext"]
        self.assertEqual([record["input"]["id"] for record in body_records(context)], [good.id])
        self.assertIn('"error": "stored_text_invalid"', context)
        self.assertIn(input_notice(bad.id, bad.session_id, self.owner), context)
        self.assertIsNone(timing_for(self.store, bad.id).received_at)
        self.assertEqual(self.inputs.get(good.id).state, "queued")
