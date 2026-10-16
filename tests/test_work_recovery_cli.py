import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from doro.application.work_bridge import WorkBridge
from doro.domain.models import OwnerRoute
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.serde import encode_session
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]
OWNER = "0f9bb165-0eaf-4e5e-92dd-236fda924d7a"


class WorkRecoveryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copy(ROOT / "orchestrator.toml", self.root)
        shutil.copytree(ROOT / "roles", self.root / "roles")
        self.store = LocalStore(self.root / ".doro")
        config = load_config(self.root / "orchestrator.toml")
        task = parse_task({**public_task(), "allowed_providers": ["claude"]})
        self.session = WorkBridge(config, self.store, ExternalRunner(), lambda _: None).start(task, "Original draft")
        self.store.bind(OwnerRoute(self.session.id, OWNER, "Recovery example"))
        self.env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PATH": "", "CODEX_THREAD_ID": OWNER}
        (self.root / "roles/claude.md").write_text("Updated public reviewer role")
        (self.root / "task.json").write_text(json.dumps(task.to_dict()))
        (self.root / "draft.md").write_text("Explicit approved public revision\r\n")
        (self.root / "reason.txt").write_text("Human requested existing session recovery")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        code = "from pathlib import Path; from doro.interface.cli import main; raise SystemExit(main(Path(__import__('sys').argv.pop(1))))"
        return subprocess.run([sys.executable, "-c", code, str(self.root), "work", *arguments],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def flags(self) -> list[str]:
        result = self.run_cli("status", self.session.id)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        def digest(name: str) -> str:
            return hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        return ["recover", self.session.id, "--owner-thread", OWNER,
                "--checkpoint", self.session.checkpoints[-1].id,
                "--expected-state", status["session_sha256"], "--expected-config", status["current_fingerprint"],
                "--task", str(self.root / "task.json"), "--task-sha256", digest("task.json"),
                "--draft", str(self.root / "draft.md"), "--draft-sha256", digest("draft.md"),
                "--reason", str(self.root / "reason.txt")]

    def test_exact_owner_and_byte_bound_packet_recover_without_approving_or_calling(self) -> None:
        flags = self.flags()
        result = self.run_cli(*flags)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertTrue(state["configuration_matches"])
        self.assertEqual(state["configuration_recoveries"], 1)
        recovered = self.store.load(self.session.id)
        self.assertEqual(recovered.status, "awaiting_approval")
        self.assertEqual(recovered.checkpoints, self.session.checkpoints)
        self.assertEqual(recovered.turns[0], self.session.turns[0])
        self.assertEqual(recovered.turns[1].text, "Explicit approved public revision\r\n")
        self.assertEqual(recovered.calls, {})
        repeated = self.run_cli(*flags)
        self.assertEqual(repeated.returncode, 1)
        self.assertEqual(len(self.store.load(self.session.id).recoveries), 1)
        decided = self.run_cli("decide", self.session.id, "--checkpoint", self.session.checkpoints[-1].id,
                               "--decision", "approve")
        self.assertEqual(decided.returncode, 0, decided.stderr)
        self.assertEqual(self.store.load(self.session.id).checkpoints[0].decision, "approve")
        self.assertEqual(self.store.load(self.session.id).calls, {})

    def test_changed_packet_wrong_owner_and_null_packet_have_no_write_side_effect(self) -> None:
        flags = self.flags()
        before = encode_session(self.store.load(self.session.id))
        self.env["CODEX_THREAD_ID"] = "d344876b-990c-4360-9aa2-d5063ff64298"
        denied = self.run_cli(*flags)
        self.assertEqual(denied.returncode, 1)
        self.assertIn("owner", denied.stderr)
        self.env["CODEX_THREAD_ID"] = OWNER
        (self.root / "draft.md").write_text("Different public text after inspection")
        denied = self.run_cli(*flags)
        self.assertEqual(denied.returncode, 1)
        self.assertIn("Approved input file changed", denied.stderr)
        (self.root / "task.json").write_text("null")
        denied = self.run_cli(*self.flags())
        self.assertEqual(denied.returncode, 1)
        self.assertEqual(encode_session(self.store.load(self.session.id)), before)
