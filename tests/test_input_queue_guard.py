from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from doro.application.work_bridge import WorkBridge
from doro.domain.models import OwnerRoute
from doro.domain.validation import parse_task
from doro.domain.work_delivery import DeliveryState, input_notice, parse_input_notice
from doro.infrastructure.config import load_config
from doro.infrastructure.delivery_store import DeliveryOutbox
from doro.infrastructure.input_notifications import hook_notice
from doro.infrastructure.input_queue_guard import GUARD_INPUT_LIMIT, guard_notice
from doro.infrastructure.input_store import LocalInputStore
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class InputQueueGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = LocalStore(Path(temporary.name) / ".doro")
        shutil.copytree(ROOT / "roles", self.store.root.parent / "roles")
        self.runner = ExternalRunner()
        self.bridge = WorkBridge(load_config(ROOT / "orchestrator.toml"), self.store, self.runner, lambda _: None)
        self.session = self.bridge.start(parse_task({**public_task(), "allowed_providers": ["claude"]}), "Draft")
        self.owner = str(uuid4())
        self.store.bind(OwnerRoute(self.session.id, self.owner, "Queue guard"))
        self.inputs = LocalInputStore(self.store)
        self.token = self.inputs.register_ui(self.session.id)
        self.outbox = DeliveryOutbox(self.store)
        self.note = self.inputs.post(self.session.id, "Private local input", self.session.checkpoints[-1].id,
                                     self.token, str(uuid4()))
        self.prompt = input_notice(self.note.id, self.session.id, self.owner)

    def event(self, **changes):
        return {"hook_event_name": "UserPromptSubmit", "session_id": self.owner,
                "turn_id": str(uuid4()), "prompt": self.prompt, **changes}

    def guard(self, **changes):
        return guard_notice(self.store.root, None, StringIO(json.dumps(self.event(**changes))))

    def finish(self) -> None:
        self.inputs.acknowledge(self.note.id, self.owner, "Actual owning Work response")

    def invoke(self, payload: str):
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        environment.pop("CODEX_THREAD_ID", None)
        script = ("import sys; from pathlib import Path; from doro.interface.cli import main; "
                  "root=Path(sys.argv.pop(1)); raise SystemExit(main(root))")
        return subprocess.run([sys.executable, "-c", script, str(self.store.root.parent),
                               "--config", str(ROOT / "orchestrator.toml"), "inputs", "guard-hook"],
                              input=payload, capture_output=True, text=True, env=environment, timeout=5)

    def test_unhandled_and_received_but_unanswered_inputs_still_reach_work(self) -> None:
        self.assertEqual(self.guard(), {})
        self.outbox.claim(self.note)
        self.outbox.complete(self.note.id, DeliveryState.QUEUED, str(uuid4()))
        self.assertEqual(self.guard(), {})
        self.inputs.receive(self.note.id, self.owner)
        self.assertEqual(self.guard(), {})
        self.finish()
        self.assertEqual(self.guard(), {"continue": False})
        self.assertEqual(self.inputs.get(self.note.id).response, "Actual owning Work response")
        self.assertEqual(self.runner.prompts, [])

    def test_only_the_exact_single_transport_envelope_is_suppressed(self) -> None:
        self.finish()
        fields = json.loads(self.prompt.split("DORO_INPUT ", 1)[1])
        prompts = [None, "", "ordinary human input", self.prompt + "\nplease continue",
                   "please inspect\n" + self.prompt, self.prompt + "\n" + self.prompt,
                   self.prompt + "\n", self.prompt.replace("\n", "\r\n"),
                   "$doro-orchestration\nDORO_INPUT {", self.prompt.replace(self.note.id, str(uuid4()))]
        for changes in ({"version": True}, {"version": "1"}, {"version": 2},
                        {"input_id": None}, {"session_id": str(uuid4())}, {"extra": "instruction"}):
            prompts.append("$doro-orchestration\nDORO_INPUT " + json.dumps({**fields, **changes}))
        for prompt in prompts:
            self.assertEqual(self.guard(prompt=prompt), {}, repr(prompt))
        self.assertEqual(parse_input_notice(self.prompt), (self.note.id, self.session.id, self.owner))
        self.assertEqual(self.guard(), {"continue": False})

    def test_registered_owner_hook_identity_and_subagent_guards_all_have_to_agree(self) -> None:
        self.finish()
        for changes in ({"session_id": str(uuid4())}, {"hook_event_name": "Stop"},
                        {"agent_id": None}, {"agent_id": ""}, {"agent_type": None}, {"agent_type": "worker"}):
            self.assertEqual(self.guard(**changes), {})
        for owner in ("", str(uuid4())):
            self.assertEqual(guard_notice(self.store.root, owner, StringIO(json.dumps(self.event()))), {})
        self.assertEqual(guard_notice(self.store.root, self.owner, StringIO(json.dumps(self.event()))),
                         {"continue": False})
        with self.store.connect() as connection:
            connection.execute("UPDATE owners SET thread_id=?", (str(uuid4()),))
        self.assertEqual(self.guard(), {})

    def test_exact_canonical_identifiers_are_required_and_new_input_is_not_hidden(self) -> None:
        self.finish()
        for original in (self.note.id, self.session.id, self.owner):
            self.assertEqual(self.guard(prompt=self.prompt.replace(original, original.upper())), {})
        new = self.inputs.post(self.session.id, "New human request", self.session.checkpoints[-1].id,
                               self.token, str(uuid4()))
        self.assertEqual(self.guard(prompt=input_notice(new.id, new.session_id, self.owner)), {})
        self.assertEqual(self.guard(), {"continue": False})
        self.assertEqual(self.inputs.get(new.id).state, "queued")

    def test_guard_is_read_only_idempotent_and_does_not_need_the_writer_lock(self) -> None:
        self.finish()
        with self.store.connect() as connection:
            before = tuple(connection.iterdump())
            connection.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.guard(), range(4)))
            self.assertEqual(results, [{"continue": False}] * 4)
            self.assertEqual(tuple(connection.iterdump()), before)
        self.assertEqual(self.bridge.store.load(self.session.id).status, "awaiting_approval")

    def test_missing_legacy_or_oversized_inputs_pass_without_initializing_state(self) -> None:
        missing = self.store.root / "absent"
        self.assertEqual(guard_notice(missing, None, StringIO(json.dumps(self.event()))), {})
        self.assertFalse(missing.exists())
        self.assertEqual(guard_notice(self.store.root, None, StringIO("x" * (GUARD_INPUT_LIMIT + 1))), {})
        with self.store.connect() as connection:
            connection.execute("DROP TABLE work_deliveries")
        self.assertEqual(self.guard(), {})
        with self.store.connect() as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='work_deliveries'").fetchone())

    def test_both_delivery_orders_keep_the_original_input_and_block_the_late_echo(self) -> None:
        self.outbox.claim(self.note)
        # PostToolUse wins the race before official queue acceptance is recorded.
        event = {"hook_event_name": "PostToolUse", "session_id": self.owner, "turn_id": str(uuid4())}
        first = hook_notice(self.store.root, None, StringIO(json.dumps(event)))
        self.assertIn(self.note.id, first["hookSpecificOutput"]["additionalContext"])
        self.inputs.receive(self.note.id, self.owner)
        self.finish()
        self.assertEqual(self.outbox.complete(self.note.id, DeliveryState.QUEUED, str(uuid4())).state,
                         DeliveryState.RECEIVED)
        self.assertEqual(self.guard(), {"continue": False})
        # Official queue wins first: it must pass, then PostToolUse must not re-notify it.
        new = self.inputs.post(self.session.id, "Queue first", self.session.checkpoints[-1].id,
                               self.token, str(uuid4()))
        self.outbox.claim(new)
        self.outbox.complete(new.id, DeliveryState.QUEUED, str(uuid4()))
        self.assertEqual(self.guard(prompt=input_notice(new.id, new.session_id, self.owner)), {})
        self.inputs.receive(new.id, self.owner)
        self.assertEqual(hook_notice(self.store.root, None, StringIO(json.dumps(event))), {})
        self.inputs.acknowledge(new.id, self.owner, "Queue input handled")
        self.assertEqual(self.guard(prompt=input_notice(new.id, new.session_id, self.owner)), {"continue": False})

    def test_real_database_failure_is_reported_instead_of_silently_suppressing_input(self) -> None:
        broken = self.store.root / "broken"
        broken.mkdir()
        (broken / "sessions.sqlite3").write_text("not a database")
        with self.assertRaises(sqlite3.DatabaseError):
            guard_notice(broken, None, StringIO(json.dumps(self.event())))

    def test_cli_suppresses_only_acknowledged_input_with_no_extra_output_or_private_text(self) -> None:
        pending = self.invoke(json.dumps(self.event()))
        self.assertEqual((pending.returncode, json.loads(pending.stdout), pending.stderr), (0, {}, ""))
        self.finish()
        handled = self.invoke(json.dumps(self.event()))
        self.assertEqual((handled.returncode, json.loads(handled.stdout), handled.stderr),
                         (0, {"continue": False}, ""))
        self.assertNotIn(self.note.text, handled.stdout + handled.stderr)
        self.assertNotIn(self.token, handled.stdout + handled.stderr)

    def test_cli_payload_and_database_errors_are_visible_nonblocking_exit_one(self) -> None:
        for payload in ("", "null", "[]", "{"):
            failed = self.invoke(payload)
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(failed.stdout, "")
            self.assertIn("DORO ERROR:", failed.stderr)
        with self.store.connect() as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("BEGIN EXCLUSIVE")
            locked = self.invoke(json.dumps(self.event()))
        self.assertEqual((locked.returncode, locked.stdout), (1, ""))
        self.assertIn("database is locked", locked.stderr)
        self.assertEqual(self.inputs.get(self.note.id).state, "queued")
        self.assertEqual(self.runner.prompts, [])

    def test_ordinary_prompt_never_touches_a_broken_or_symlinked_state_directory(self) -> None:
        self.finish()
        actual = self.store.root.with_name("actual-state")
        self.store.root.rename(actual)
        self.store.root.symlink_to(actual, target_is_directory=True)
        ordinary = self.invoke(json.dumps(self.event(prompt="Fresh human question")))
        self.assertEqual((ordinary.returncode, json.loads(ordinary.stdout), ordinary.stderr), (0, {}, ""))
        guarded = self.invoke(json.dumps(self.event()))
        self.assertEqual((guarded.returncode, guarded.stdout), (1, ""))
        self.assertIn("cannot be a symlink", guarded.stderr)
