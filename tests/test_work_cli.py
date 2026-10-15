import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from doro.application.work_bridge import WorkBridge
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class WorkCliTests(unittest.TestCase):
    def test_review_without_explicit_send_has_no_model_or_authentication_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(ROOT / "orchestrator.toml", root)
            shutil.copytree(ROOT / "roles", root / "roles")
            config = load_config(root / "orchestrator.toml")
            store = LocalStore(root / ".doro")
            task = parse_task({**public_task(), "allowed_providers": ["claude"]})
            session = WorkBridge(config, store, ExternalRunner(), lambda _: None).start(task, "Public draft")
            code = "from pathlib import Path; from doro.interface.cli import main; raise SystemExit(main(Path(__import__('sys').argv.pop(1))))"
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PATH": ""}
            for flags, expected in (([], "requires --send"), (["--send"], "approval")):
                result = subprocess.run([sys.executable, "-c", code, str(root), "work", "review", session.id, *flags],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)
            self.assertEqual(store.load(session.id).calls, {})
            self.assertEqual(store.load(session.id).status, "awaiting_approval")
