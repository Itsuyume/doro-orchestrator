from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.conversation import conversation, context_summary
from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.domain.work import validate_work
from doro.infrastructure.config import load_config
from doro.infrastructure.new_task_chat import attach_chat, update_chat
from doro.infrastructure.new_task_store import NewTaskStore
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class NewTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = load_config(ROOT / "orchestrator.toml")
        self.root = Path(tmp.name)
        self.sessions = LocalStore(self.root / ".doro")
        self.runner = ExternalRunner()
        bridge = WorkBridge(self.config, self.sessions, self.runner, lambda _: None)
        self.source = bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Draft")
        self.owner = str(uuid4())
        self.sessions.bind(OwnerRoute(self.source.id, self.owner, "Source"))
        self.store = NewTaskStore(self.sessions)
        self.token = self.store.inputs.register_ui(self.source.id)
        self.gate = self.source.checkpoints[-1].id

    def request(self, text: str = "Please start a separate task") -> str:
        client_id = str(uuid4())
        self.store.begin(self.source.id, text, client_id, self.token)
        self.store.inputs.post(self.source.id, text, self.gate, self.token, client_id)
        return client_id

    def create(self, request_id: str) -> tuple[str, str]:
        self.assertTrue(self.store.claim(request_id, self.owner))
        thread_id = str(uuid4())
        return attach_chat(self.store, request_id, self.owner, thread_id, self.config), thread_id

    def test_empty_nul_oversize_and_invalid_capability_leave_no_intent_or_input(self) -> None:
        for text, token in [("", self.token), ("   ", self.token), ("a\0b", self.token), ("a" * 2001, self.token), ("task", "wrong")]:
            with self.assertRaises(DoroError):
                self.store.begin(self.source.id, text, str(uuid4()), token)
        with self.sessions.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM new_tasks").fetchone()[0], 0)
        self.assertEqual(self.store.inputs.inputs(self.source.id), ())
        self.assertEqual(self.runner.prompts, [])

    def test_boundary_duplicate_and_different_payload(self) -> None:
        request_id = self.request("한" * 2000)
        first = self.store.get(request_id)
        self.assertEqual(self.store.begin(self.source.id, "한" * 2000, request_id, self.token), first)
        with self.assertRaisesRegex(DoroError, "different input"):
            self.store.begin(self.source.id, "different", request_id, self.token)
        self.assertEqual(len(self.store.inputs.inputs(self.source.id)), 1)
        self.assertEqual(self.sessions.load(self.source.id).checkpoints[-1].decision, "pending")

    def test_an_existing_reply_cannot_be_promoted_to_creation_intent(self) -> None:
        note_id = str(uuid4())
        self.store.inputs.post(self.source.id, "ordinary message", self.gate, self.token, note_id)
        with self.assertRaisesRegex(DoroError, "existing reply"):
            self.store.begin(self.source.id, "ordinary message", note_id, self.token)
        self.assertIsNone(self.store.find(note_id))

    def test_creation_is_claimed_once_across_concurrent_handlers(self) -> None:
        request_id = self.request()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: self.store.claim(request_id, self.owner), range(4)))
        self.assertEqual(sum(claims), 1)
        self.assertEqual(self.store.get(request_id).state, "creating")

    def test_orphan_intent_and_wrong_owner_cannot_create_a_chat(self) -> None:
        request_id = str(uuid4())
        self.store.begin(self.source.id, "task", request_id, self.token)
        with self.assertRaises(DoroError):
            self.store.claim(request_id, self.owner)
        request_id = self.request()
        with self.assertRaisesRegex(DoroError, "another GPT"):
            self.store.claim(request_id, str(uuid4()))
        with self.assertRaises(DoroError):
            attach_chat(self.store, request_id, self.owner, str(uuid4()), self.config)
        self.assertEqual(len(self.sessions.routes()), 1)

    def test_new_chat_receives_only_its_original_input_and_is_not_an_advisor_scope(self) -> None:
        request_id = self.request("My private writing request")
        session_id, thread_id = self.create(request_id)
        request = self.store.get(request_id)
        session = self.sessions.load(session_id)
        self.assertEqual(session.mode, "chat")
        self.assertEqual(self.sessions.routes()[-1].thread_id, thread_id)
        notes = self.store.inputs.inputs(session_id)
        self.assertEqual([(note.text, note.owner_thread_id) for note in notes], [("My private writing request", thread_id)])
        self.assertNotIn("private writing", session.task.message)
        self.assertEqual(request.child_input_id, notes[0].id)
        with self.assertRaisesRegex(DoroError, "not a GPT Work"):
            validate_work(self.config, session)
        self.assertEqual(self.runner.prompts, [])
        self.assertEqual(self.sessions.load(self.source.id).checkpoints[-1].decision, "pending")
        self.assertEqual(attach_chat(self.store, request_id, self.owner, thread_id, self.config), session_id)
        self.assertEqual(len(self.sessions.routes()), 2)

    def test_uncertain_creation_never_automatically_retries_and_can_record_a_known_result(self) -> None:
        request_id = self.request()
        self.assertTrue(self.store.claim(request_id, self.owner))
        self.store.failed(request_id, self.owner, "Tool response lost", True)
        self.assertFalse(self.store.claim(request_id, self.owner))
        self.assertEqual(self.store.get(request_id).state, "unknown")
        thread_id = str(uuid4())
        session_id = attach_chat(self.store, request_id, self.owner, thread_id, self.config)
        self.assertEqual(self.store.get(request_id).state, "created")
        self.assertEqual(self.store.get(request_id).error, "")
        self.assertEqual(self.sessions.load(session_id).calls, {})

    def test_broker_cannot_be_reused_as_new_task_and_child_cannot_create_more_chats(self) -> None:
        request_id = self.request()
        self.assertTrue(self.store.claim(request_id, self.owner))
        with self.assertRaises(DoroError):
            attach_chat(self.store, request_id, self.owner, self.owner, self.config)
        child = str(uuid4())
        attach_chat(self.store, request_id, self.owner, child, self.config)
        with self.assertRaises(DoroError):
            self.store.claim(request_id, child)

    def test_progress_and_final_are_visible_idempotent_and_bound_to_the_child(self) -> None:
        request_id = self.request()
        session_id, child = self.create(request_id)
        with self.assertRaises(DoroError):
            update_chat(self.store, request_id, self.owner, "wrong", True)
        update_chat(self.store, request_id, child, "Working", False)
        update_chat(self.store, request_id, child, "Finished", True)
        update_chat(self.store, request_id, child, "Finished", True)
        session = self.sessions.load(session_id)
        notes = self.store.inputs.inputs(session_id)
        view = conversation(self.config, session, inputs=notes, input_enabled=True)
        self.assertEqual([message.text for message in view.messages], ["Please start a separate task", "Working", "Finished"])
        self.assertEqual(len(session.turns), 2)
        self.assertTrue(view.messages[0].from_user)
        self.assertFalse(view.messages[-1].from_user)
        self.assertTrue(context_summary(session, "Task", notes).finished)
        self.assertEqual(self.store.inputs.pending(session_id, child), ())
        self.assertEqual(self.runner.prompts, [])
