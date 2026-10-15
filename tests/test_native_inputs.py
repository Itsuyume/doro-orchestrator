from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.conversation import conversation
from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore
from doro.interface.input_cli import wait_inputs
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class NativeInputTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = load_config(ROOT / "orchestrator.toml")
        self.sessions = LocalStore(Path(tmp.name))
        self.runner = ExternalRunner()
        self.bridge = WorkBridge(self.config, self.sessions, self.runner, lambda _: None)
        self.session = self.bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Public draft")
        self.owner = str(uuid4())
        self.sessions.bind(OwnerRoute(self.session.id, self.owner, "입력 시험"))
        self.inputs = LocalInputStore(self.sessions)
        self.token = self.inputs.register_ui(self.session.id)
        self.checkpoint = self.session.checkpoints[-1].id

    def test_empty_null_oversize_wrong_instance_and_stale_question_have_no_effect(self) -> None:
        for text, token, checkpoint in [("", self.token, self.checkpoint), ("\0", self.token, self.checkpoint),
                                         ("x" * 2001, self.token, self.checkpoint),
                                         ("message", "wrong-instance", self.checkpoint), ("message", self.token, str(uuid4()))]:
            with self.assertRaises(DoroError):
                self.inputs.post(self.session.id, text, checkpoint, token, str(uuid4()))
        self.assertEqual(self.inputs.inputs(self.session.id), ())
        self.assertEqual(self.sessions.load(self.session.id).status, "awaiting_approval")
        self.assertEqual(self.runner.prompts, [])

    def test_concurrent_reposts_are_one_record_and_different_content_is_rejected(self) -> None:
        note_id = str(uuid4())
        def post():
            return self.inputs.post(self.session.id, "중간 질문", self.checkpoint, self.token, note_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: post(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(len(self.inputs.inputs(self.session.id)), 1)
        with self.assertRaises(DoroError):
            self.inputs.post(self.session.id, "different message", self.checkpoint, self.token, note_id)

    def test_ordinary_chat_and_explicit_approval_are_distinct_and_never_automatically_decide(self) -> None:
        chat = self.inputs.post(self.session.id, "승인이라는 단어가 든 일반 질문", self.checkpoint, self.token, str(uuid4()))
        approval = self.inputs.post(self.session.id, "이 범위 승인해도로", self.checkpoint, self.token, str(uuid4()), "approve")
        self.assertEqual(chat.decision, "")
        self.assertEqual(approval.decision, "approve")
        self.assertEqual(self.sessions.load(self.session.id).checkpoints[-1].decision, "pending")
        self.bridge.decide(self.session.id, self.checkpoint, "approve")
        repeated = self.inputs.post(self.session.id, approval.text, self.checkpoint, self.token, approval.id, "approve")
        self.assertEqual(repeated.id, approval.id)
        with self.assertRaises(DoroError):
            self.inputs.post(self.session.id, "late approval", self.checkpoint, self.token, str(uuid4()), "approve")
        self.assertEqual(self.runner.prompts, [])

    def test_owner_reads_and_replies_in_same_local_conversation_without_external_calls(self) -> None:
        note = self.inputs.post(self.session.id, "로컬에서만 볼 개인 질문", self.checkpoint, self.token, str(uuid4()))
        with self.assertRaises(DoroError):
            self.inputs.pending(self.session.id, str(uuid4()))
        with self.assertRaises(DoroError):
            self.inputs.acknowledge(note.id, str(uuid4()))
        self.assertEqual(len(self.inputs.pending(self.session.id, self.owner)), 1)
        self.inputs.acknowledge(note.id, self.owner, "도로가 읽었도로. 외부 모델에는 보내지 않았도로.")
        self.assertEqual(self.inputs.pending(self.session.id, self.owner), ())
        view = conversation(self.config, self.sessions.load(self.session.id), inputs=self.inputs.inputs(self.session.id), input_enabled=True)
        self.assertEqual([m.sender for m in view.messages][2:4], ["나", "도로 · GPT Work"])
        self.assertEqual(view.messages[2].state, "도로 확인")
        self.assertTrue(view.messages[2].from_user)
        self.assertFalse(view.messages[3].from_user)
        self.assertEqual(self.runner.prompts, [])
        self.assertNotIn(self.token, str(view))

    def test_second_decision_with_new_id_is_rejected_but_chat_is_still_allowed(self) -> None:
        self.inputs.post(self.session.id, "approve", self.checkpoint, self.token, str(uuid4()), "approve")
        with self.assertRaisesRegex(DoroError, "already waiting"):
            self.inputs.post(self.session.id, "reject", self.checkpoint, self.token, str(uuid4()), "reject")
        self.inputs.post(self.session.id, "extra context", self.checkpoint, self.token, str(uuid4()))
        view = conversation(self.config, self.session, inputs=self.inputs.inputs(self.session.id))
        self.assertTrue(view.approval.response_pending)
        self.assertEqual(view.approval.response_decision, "approve")
        self.assertEqual(len(self.inputs.inputs(self.session.id)), 2)
        self.assertEqual(self.sessions.load(self.session.id).checkpoints[-1].decision, "pending")
        self.assertEqual(self.runner.prompts, [])

    def test_expired_and_other_collaboration_tokens_are_rejected(self) -> None:
        other = self.bridge.start(self.session.task, "Other public draft")
        self.sessions.bind(OwnerRoute(other.id, self.owner, "다른 시험"))
        with self.assertRaises(DoroError):
            self.inputs.post(other.id, "wrong destination", other.checkpoints[-1].id, self.token, str(uuid4()))
        with self.sessions.connect() as connection:
            connection.execute("UPDATE ui_tokens SET expires=0")
        with self.assertRaises(DoroError):
            self.inputs.post(self.session.id, "expired", self.checkpoint, self.token, str(uuid4()))
        self.assertEqual(self.inputs.inputs(self.session.id), ())

    def test_wait_returns_queued_input_without_consuming_and_rejects_bad_timeout(self) -> None:
        self.assertEqual(wait_inputs(self.inputs, self.session.id, self.owner, 0.001), [])
        for timeout in (0, -1, 56, float("nan")):
            with self.assertRaises(ValueError):
                wait_inputs(self.inputs, self.session.id, self.owner, timeout)
        self.inputs.post(self.session.id, "중간 지시", self.checkpoint, self.token, str(uuid4()))
        result = wait_inputs(self.inputs, self.session.id, self.owner, 55)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(self.inputs.pending(self.session.id, self.owner)), 1)
        self.assertEqual(self.runner.prompts, [])
