from collections.abc import Callable
import json
from pathlib import Path
import tempfile
import unittest

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, Reply
from doro.domain.progress import progress
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.process import ProcessResult
from doro.infrastructure.protocol import decode_reply
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.streaming import ClaudeTextStream
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


def delta(text: str) -> bytes:
    return (json.dumps({"type": "stream_event", "event": {
        "type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}},
        ensure_ascii=False) + "\n").encode()


class ObservedRunner:
    def __init__(self, store: LocalStore, session_id: str, fail: bool = False) -> None:
        self.store, self.session_id, self.fail = store, session_id, fail
        self.observed: list[str] = []

    def call(self, name: str, prompt: str, cwd: Path, timeout: float,
             on_text: Callable[[str], None] | None = None) -> Reply:
        assert on_text is not None
        on_text("첫 문장\n")
        live = self.store.load(self.session_id)
        self.observed.append(live.exchanges[-1].output)
        assert live.exchanges[-1].input == prompt
        assert live.status == "running"
        if self.fail:
            raise DoroError("Provider stopped before final result")
        on_text("다음 문장")
        return Reply("첫 문장\n다음 문장", 20, 0.01, "public-native-id")


class StreamingTests(unittest.TestCase):
    def test_utf8_split_events_expose_only_text_and_never_internal_thinking(self) -> None:
        pieces: list[str] = []
        parser = ClaudeTextStream(pieces.append)
        hidden = json.dumps({"type": "stream_event", "event": {
            "type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "HIDDEN"}}}).encode()+b"\n"
        payload = hidden + delta("공개 응답\n")
        for value in payload:
            parser.feed(bytes([value]))
        parser.finish()
        self.assertEqual(pieces, ["공개 응답\n"])

    def test_malformed_incomplete_and_tool_events_fail_visibly(self) -> None:
        tool = json.dumps({"type": "stream_event", "event": {
            "type": "content_block_start", "content_block": {"type": "tool_use"}}}).encode()+b"\n"
        for payload in (b"invalid\n", b'{"type":', tool):
            with self.subTest(payload=payload), self.assertRaises(DoroError):
                parser = ClaudeTextStream(lambda _: None)
                parser.feed(payload)
                parser.finish()

    def test_stream_requires_unique_authoritative_success_result(self) -> None:
        result = {"type": "result", "subtype": "success", "is_error": False,
                  "result": "Final public answer", "usage": {"input_tokens": 8, "output_tokens": 4},
                  "total_cost_usd": 0.01, "session_id": "native-id"}
        raw = (delta("Partial public answer") + (json.dumps(result)+"\n").encode()).decode()
        reply = decode_reply("claude", ProcessResult(raw, "", 0))
        self.assertEqual((reply.text, reply.tokens), ("Final public answer", 12))
        pretty = decode_reply("claude", ProcessResult(json.dumps(result, indent=2), "", 0))
        self.assertEqual(pretty, reply)
        for output in (delta("Partial only").decode(), raw+json.dumps(result)+"\n"):
            with self.subTest(output=output), self.assertRaises(DoroError):
                decode_reply("claude", ProcessResult(output, "", 0))

    def test_exact_input_and_partial_output_are_saved_before_completion_and_failure(self) -> None:
        config = load_config(ROOT / "orchestrator.toml")
        task = parse_task({**public_task(), "allowed_providers": ["claude"], "context": "Explicit public context"})
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                store = LocalStore(Path(tmp))
                initial = WorkBridge(config, store, ObservedRunner(store, "unused"), lambda _: None)
                session = initial.start(task, "Public draft")
                initial.decide(session.id, session.checkpoints[-1].id, "approve")
                runner = ObservedRunner(store, session.id, fail)
                bridge = WorkBridge(config, store, runner, lambda _: None)
                if fail:
                    with self.assertRaises(DoroError):
                        bridge.review(session.id)
                else:
                    bridge.review(session.id)
                saved = store.load(session.id)
                self.assertEqual(runner.observed, ["첫 문장\n"])
                self.assertEqual(saved.exchanges[-1].status, "failed" if fail else "completed")
                self.assertEqual(len(saved.turns), 1 if fail else 2)
                state = progress(config, saved)
                self.assertEqual(state["context"], "Explicit public context")
                self.assertIn("Public draft", saved.exchanges[-1].input)
