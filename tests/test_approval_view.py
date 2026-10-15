from dataclasses import asdict
import unittest
from uuid import uuid4

from doro.application.conversation import context_summary, conversation, conversation_text
from doro.domain.checkpoints import request_checkpoint
from doro.domain.models import DoroError
from doro.infrastructure.serde import decode_checkpoint
import test_native_inputs as inputs_fixture


class ApprovalViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = inputs_fixture.NativeInputTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_short_summary_and_complete_detail_are_separate_and_legacy_remains_readable(self) -> None:
        f = self.fixture
        f.bridge.decide(f.session.id, f.checkpoint, "approve")
        detail = "Public implementation detail. " * 80
        brief = "승인창을 분리하고 모델 선택을 추가. 로컬 실행기만 반영. 백업 가능."
        session = f.bridge.checkpoint(f.session.id, "apply", detail, brief)
        view = conversation(f.config, session)
        self.assertEqual((view.approval.brief, view.approval.details), (brief, detail))
        self.assertFalse(any(message.text == detail for message in view.messages))
        self.assertIn(detail, conversation_text(view))
        legacy = asdict(session.checkpoints[-1])
        legacy.pop("brief")
        self.assertEqual(decode_checkpoint(legacy).summary, detail)
        self.assertEqual(decode_checkpoint(legacy).brief, "")

    def test_invalid_brief_preserves_session_and_empty_brief_does_not_invent_summary(self) -> None:
        f = self.fixture
        session = f.bridge.decide(f.session.id, f.checkpoint, "approve")
        before = asdict(session)
        for brief in (" " * 20, "a" * 281, "api_key=privateCredential"):
            with self.subTest(brief=brief), self.assertRaises(DoroError):
                request_checkpoint(session, "apply", "Public details", brief)
            self.assertEqual(asdict(session), before)
        request_checkpoint(session, "apply", "Public details")
        self.assertEqual(conversation(f.config, session).approval.brief, "")

    def test_answered_question_is_removed_without_claiming_application_happened(self) -> None:
        f = self.fixture
        session = f.bridge.decide(f.session.id, f.checkpoint, "reject")
        self.assertIsNone(conversation(f.config, session).approval)
        self.assertEqual(f.runner.prompts, [])

    def test_start_can_show_authored_brief_while_preserving_complete_scope(self) -> None:
        f = self.fixture
        scope = "Public scope and transmission details. " * 25
        session = f.bridge.start(f.session.task, "Public draft", scope, brief="공개 UI 구조만 Claude에 검토 요청")
        view = conversation(f.config, session)
        self.assertEqual((view.approval.brief, view.approval.details), ("공개 UI 구조만 Claude에 검토 요청", scope))
        self.assertEqual(session.status, "awaiting_approval")
        self.assertEqual(f.runner.prompts, [])

    def test_queued_answer_clears_action_badge_but_preserves_human_receipt_and_pending_work(self) -> None:
        f = self.fixture
        self.assertTrue(context_summary(f.session, "Task", ()).needs_input)
        f.inputs.post(f.session.id, "내 질문", f.checkpoint, f.token, str(uuid4()))
        self.assertTrue(context_summary(f.session, "Task", f.inputs.inputs(f.session.id)).needs_input)
        f.inputs.post(f.session.id, "이 범위 승인해도로", f.checkpoint, f.token, str(uuid4()), "approve")
        notes = f.inputs.inputs(f.session.id)
        context = context_summary(f.session, "Task", notes)
        self.assertFalse(context.needs_input)
        self.assertEqual(context.queued_inputs, 2)
        view = conversation(f.config, f.session, inputs=notes)
        self.assertEqual([m.text for m in view.messages if m.from_user], ["내 질문", "이 범위 승인해도로"])
        self.assertTrue(all(not m.from_user for m in view.messages if m.sender != "나"))
        self.assertEqual(f.sessions.load(f.session.id).checkpoints[-1].decision, "pending")
        self.assertEqual(f.runner.prompts, [])
