import json
import unittest

from doro.domain.models import DoroError
from doro.infrastructure.process import ProcessResult
from doro.infrastructure.protocol import decode_reply


class ProtocolTests(unittest.TestCase):
    def test_codex_decodes_only_completed_message_and_usage(self) -> None:
        events = [{"type": "thread.started", "thread_id": "native-id"},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "solution"}},
                  {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}]
        reply = decode_reply("codex", ProcessResult("\n".join(map(json.dumps, events)), "", 0))
        self.assertEqual((reply.text, reply.tokens, reply.cost_usd), ("solution", 15, None))
        self.assertEqual(reply.native_session_id, "native-id")

    def test_claude_error_with_success_subtype_is_still_a_failure(self) -> None:
        output = {"subtype": "success", "is_error": True, "result": "OAuth expired"}
        with self.assertRaisesRegex(DoroError, "OAuth expired"):
            decode_reply("claude", ProcessResult(json.dumps(output), "", 0))

    def test_claude_actual_model_is_retained_not_inferred_from_requested_alias(self) -> None:
        events = [{"type": "assistant", "message": {"model": "claude-opus-5-5"}},
                  {"type": "result", "subtype": "success", "is_error": False, "result": "review", "session_id": "n",
                   "usage": {"input_tokens": 20, "output_tokens": 8}, "total_cost_usd": 0.01}]
        reply = decode_reply("claude", ProcessResult("\n".join(map(json.dumps, events)), "", 0))
        self.assertEqual((reply.model, reply.tokens), ("claude-opus-5-5", 28))

    def test_malformed_incomplete_and_forbidden_tool_outputs_fail(self) -> None:
        tool = {"type": "item.completed", "item": {"type": "command_execution"}}
        for output in ("not-json", "{}", json.dumps(tool)):
            with self.subTest(output=output), self.assertRaises(DoroError):
                decode_reply("codex", ProcessResult(output, "", 0))

    def test_agy_contract_parser_does_not_invoke_agy(self) -> None:
        output = {"status": "SUCCESS", "response": "public idea", "conversation_id": "future-id",
                  "usage": {"total_tokens": 30}}
        reply = decode_reply("agy", ProcessResult(json.dumps(output), "", 0))
        self.assertEqual(reply.text, "public idea")
        self.assertEqual(reply.tokens, 30)
