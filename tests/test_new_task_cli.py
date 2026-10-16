import io
import json
import os
import sys
from unittest.mock import patch
import unittest
from uuid import uuid4

from doro.domain.models import DoroError
from doro.interface.cli import parser
from doro.interface.new_task_cli import run_new_task
import test_new_tasks as fixtures


class NewTaskCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.NewTaskTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.log = self.root / "queue.jsonl"
        executable = self.root / "bin/codex"
        executable.parent.mkdir()
        executable.write_text(f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
            f"with Path({str(self.log)!r}).open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
            f"print('Queued message {uuid4()} for thread '+sys.argv[sys.argv.index('--thread')+1]+'.')\n")
        executable.chmod(0o700)
        self.environment = {"PATH": str(executable.parent) + os.pathsep + os.environ.get("PATH", ""),
                            "DORO_CHAT_CAPABILITY": self.fixture.token}

    def call(self, *arguments: str, payload: object = None, token: str | None = None) -> object:
        args = parser(self.root).parse_args(["new-task", *arguments])
        data = json.dumps(payload).encode() if payload is not None else b""
        with patch.dict(os.environ, {**self.environment, **({"DORO_CHAT_CAPABILITY": token} if token is not None else {})}):
            with patch("sys.stdin", io.TextIOWrapper(io.BytesIO(data))):
                return run_new_task(args, self.fixture.config, self.root)

    def test_post_and_repost_use_one_id_only_wake_and_do_not_approve_existing_question(self) -> None:
        request_id = str(uuid4())
        payload = {"text": "My separate private request", "client_id": request_id}
        result = self.call("request", "--source-session", self.fixture.source.id, payload=payload)
        self.assertEqual(result["delivery"]["state"], "queued")
        self.call("request", "--source-session", self.fixture.source.id, payload=payload)
        sent = self.log.read_text().splitlines()
        self.assertEqual(len(sent), 1)
        self.assertNotIn(payload["text"], sent[0])
        self.assertNotIn(self.fixture.token, sent[0])
        self.assertIn(request_id, sent[0])
        self.assertEqual(self.fixture.sessions.load(self.fixture.source.id).checkpoints[-1].decision, "pending")
        self.assertEqual(self.fixture.runner.prompts, [])

    def test_status_needs_ui_capability_and_creation_needs_the_correct_broker(self) -> None:
        request_id = self.fixture.request()
        with self.assertRaises(DoroError):
            self.call("status", request_id, token="wrong")
        with self.assertRaises(DoroError):
            self.call("claim", request_id, "--owner-thread", str(uuid4()))
        result = self.call("claim", request_id, "--owner-thread", self.fixture.owner)
        self.assertTrue(result["claimed"])
        child = str(uuid4())
        created = self.call("created", request_id, "--owner-thread", self.fixture.owner, "--thread", child)
        status = self.call("status", request_id)
        self.assertEqual(status["session_id"], created["session_id"])
        self.assertTrue(status["token"])
        view = self.call("wait", request_id, "--owner-thread", child)
        self.assertEqual(view["input"]["text"], "Please start a separate task")
        reply = self.root / "reply.txt"
        reply.write_text("A new GPT task replied")
        self.call("update", request_id, "--owner-thread", child, "--text", str(reply), "--final")
        self.assertEqual(self.fixture.sessions.load(created["session_id"]).turns[-1].text, reply.read_text())

    def test_invalid_post_and_non_owner_get_never_wake_or_expose_input(self) -> None:
        with self.assertRaises(DoroError):
            self.call("request", "--source-session", self.fixture.source.id,
                      payload={"text": "secret", "client_id": str(uuid4())}, token="wrong")
        self.assertFalse(self.log.exists())

    def test_missing_intent_can_retry_only_when_no_original_input_exists(self) -> None:
        request_id = str(uuid4())
        result = self.call("status", request_id, "--source-session", self.fixture.source.id)
        self.assertEqual(result["state"], "not_submitted")
        self.fixture.store.inputs.post(self.fixture.source.id, "existing input", self.fixture.gate,
                                       self.fixture.token, request_id)
        result = self.call("status", request_id, "--source-session", self.fixture.source.id)
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(self.log.exists())
        request_id = self.fixture.request()
        with self.assertRaises(DoroError):
            self.call("get", request_id, "--owner-thread", str(uuid4()))
        self.assertFalse(self.log.exists())
