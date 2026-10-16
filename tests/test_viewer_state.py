from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.viewer_state import wait_for_ack, write_request
from doro.application.conversation import context_summary, conversation
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class ViewerStateTests(unittest.TestCase):
    def test_request_updates_only_one_selected_stack_and_tokens_remain_session_bound(self) -> None:
        config = load_config(ROOT / "orchestrator.toml")
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp) / ".doro")
            bridge = WorkBridge(config, store, runner, lambda _: None)
            task = parse_task({**public_task(), "allowed_providers": ["claude"]})
            a, b = bridge.start(task, "Draft A"), bridge.start(task, "Draft B")
            owner = str(uuid4())
            for session, label in [(a, "Stack A"), (b, "Stack B")]:
                store.bind(OwnerRoute(session.id, owner, label))
            receipt = write_request(store, a.id, "panel")
            path = receipt.path
            first = json.loads(path.read_text())
            write_request(store, b.id, "integrated")
            second = json.loads(path.read_text())
            with self.assertRaisesRegex(DoroError, "superseded"):
                wait_for_ack(receipt, timeout=0.1)
            self.assertNotEqual(first["request_id"], second["request_id"])
            self.assertEqual(second["session_id"], b.id)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            inputs = LocalInputStore(store)
            note = inputs.post(b.id, "Private local note for B", b.checkpoints[-1].id,
                               second["tokens"][b.id], str(uuid4()))
            self.assertEqual(inputs.pending(a.id, owner), ())
            self.assertEqual(inputs.pending(b.id, owner), (note,))
            summaries = tuple(context_summary(s, label, inputs.inputs(s.id))
                              for s, label in [(a, "Stack A"), (b, "Stack B")])
            view = conversation(config, a, "Stack A", inputs=inputs.inputs(a.id), contexts=summaries)
            packet = json.dumps(asdict(view))
            self.assertNotIn("Private local note for B", packet)
            self.assertEqual(view.contexts[1].queued_inputs, 1)
            self.assertEqual(runner.prompts, [])

    def test_request_symlink_is_rejected_without_overwriting_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = LocalStore(root / ".doro")
            directory = store.root / "native"
            directory.mkdir()
            target = root / "preserve.txt"
            target.write_text("keep")
            (directory / "viewer-request.json").symlink_to(target)
            with self.assertRaisesRegex(DoroError, "symlink"):
                write_request(store, str(uuid4()), "panel")
            self.assertEqual(target.read_text(), "keep")

    def test_missing_or_wrong_ack_never_claims_that_the_native_pet_is_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp) / ".doro")
            receipt = write_request(store, str(uuid4()), "hidden")
            with self.assertRaisesRegex(DoroError, "did not confirm"):
                wait_for_ack(receipt, timeout=0.01)
            ack = receipt.path.parent / "viewer-ack.json"
            ack.write_text(json.dumps({"request_id": receipt.request_id, "display": "hidden"}))
            wait_for_ack(receipt, timeout=0.1)
            ack.write_text("[]")
            with self.assertRaises(DoroError):
                wait_for_ack(receipt, timeout=0.1)

    def test_window_control_requires_exact_intent_ack_and_rejects_invalid_action_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp) / ".doro")
            session = str(uuid4())
            for intent, display in (("minimize", "hidden"), ("hide", "hidden")):
                receipt = write_request(store, session, display, intent=intent)
                self.assertEqual(json.loads(receipt.path.read_text())["intent"], intent)
                ack = receipt.path.parent / "viewer-ack.json"
                response = {"request_id": receipt.request_id, "display": display}
                ack.write_text(json.dumps(response))
                with self.assertRaisesRegex(DoroError, "window action"):
                    wait_for_ack(receipt, timeout=0.1)
                ack.write_text(json.dumps({**response, "intent": intent}))
                wait_for_ack(receipt, timeout=0.1)
            original = receipt.path.read_bytes()
            for invalid in ("", "launch-model", "minimize; execute"):
                with self.assertRaisesRegex(DoroError, "window action"):
                    write_request(store, session, "panel", intent=invalid)
                self.assertEqual(receipt.path.read_bytes(), original)
            self.assertEqual(store.routes(), ())
