from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from doro.application.conversation import conversation
from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, Exchange, Turn
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class ConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "orchestrator.toml")
        self.task = parse_task({**public_task(), "allowed_providers": ["claude"]})

    def test_start_shows_only_actual_request_draft_and_current_question_with_no_calls(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            bridge = WorkBridge(self.config, LocalStore(Path(tmp)), runner, lambda _: None)
            session = bridge.start(self.task, "Actual Work draft")
            view = conversation(self.config, session, "표시 시험")
            self.assertEqual(len(view.messages), 2)
            self.assertEqual(view.messages[1].text, "Actual Work draft")
            self.assertTrue(view.messages[1].main)
            self.assertIsNotNone(view.approval)
            self.assertEqual(view.approval.checkpoint_id, session.checkpoints[-1].id)
            self.assertEqual(view.approval.details, session.checkpoints[-1].summary)
            self.assertEqual(runner.prompts, [])
            self.assertEqual(session.calls, {})

    def test_failed_empty_stream_is_visible_and_successful_retry_not_duplicated(self) -> None:
        runner = ExternalRunner(fail_once=True)
        with tempfile.TemporaryDirectory() as tmp:
            bridge = WorkBridge(self.config, LocalStore(Path(tmp)), runner, lambda _: None)
            session = bridge.start(self.task, "Draft")
            bridge.decide(session.id, session.checkpoints[-1].id, "approve")
            with self.assertRaises(DoroError):
                bridge.review(session.id)
            reviewed = bridge.review(session.id)
            bridge.reply(session.id, "Actual rebuttal")
            bridge.review(session.id)
            final = bridge.finish(session.id, "Actual final")
            messages = conversation(self.config, final).messages
            self.assertEqual([m.text for m in messages if m.main], ["Draft", "Actual rebuttal", "Actual final"])
            replies = [m for m in messages if m.sender == "도로 · Claude Code"]
            self.assertEqual(len(replies), 3)
            self.assertIn("실패", replies[0].state)
            self.assertIn("Actual rebuttal", replies[-1].incoming)
            self.assertEqual(replies[-1].text, final.turns[-2].text)
            self.assertTrue(all(not message.from_user for message in messages))
            self.assertEqual(reviewed.calls, {"claude": 2})

    def test_streaming_partial_stays_partial_and_does_not_change_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = WorkBridge(self.config, LocalStore(Path(tmp)), ExternalRunner(), lambda _: None).start(self.task, "Draft")
            session = replace(session, status="running", exchanges=[Exchange("claude", "review", "Exact input", "")])
            empty = conversation(self.config, session).messages[-1]
            self.assertEqual(empty.state, "응답 생성 중")
            self.assertEqual(empty.incoming, "Exact input")
            session.exchanges[-1].output = "Partial response"
            partial = conversation(self.config, session).messages[-1]
            self.assertEqual(partial.text, "Partial response")
            self.assertEqual(partial.state, "응답 생성 중")
            self.assertEqual(empty.id, partial.id)
            self.assertEqual(len(session.turns), 1)
            self.assertEqual(session.calls, {})

    def test_completed_stream_retains_its_message_id_after_an_earlier_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = WorkBridge(self.config, LocalStore(Path(tmp)), ExternalRunner(), lambda _: None).start(self.task, "Draft")
            failed = Exchange("claude", "review", "Earlier input", "Partial failure", status="failed")
            running = Exchange("claude", "review", "Exact input", "Partial response")
            session = replace(session, status="running", exchanges=[failed, running])
            before = conversation(self.config, session).messages
            running.output += " completed"
            running.status = "completed"
            session.turns.append(Turn("claude", "review", running.output, 0, None, ""))
            session.status = "awaiting_work"
            after = conversation(self.config, session).messages
            self.assertEqual(after[-1].id, before[-1].id, "Completion cannot reset the expanded bubble or its reading anchor")
            self.assertEqual(after[-2].id, before[-2].id, "Stored failed attempts keep their existing identity")
            self.assertEqual(after[-1].id, "turn-1", "Existing completed-turn identities stay compatible")
            self.assertEqual(len({message.id for message in after}), len(after))
            self.assertEqual(after[-1].text, running.output)
