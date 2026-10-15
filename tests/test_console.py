from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from doro.interface.console import watch_progress
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class ConsoleProgressTests(unittest.TestCase):
    def test_watch_prints_only_phase_metadata_without_network_browser_or_model_calls(self) -> None:
        config = load_config(ROOT / "orchestrator.toml")
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            task = parse_task({**public_task("PRIVATE_TASK_BODY_FOR_LOCAL_TEST"), "allowed_providers": ["claude"]})
            session = WorkBridge(config, store, runner, lambda _: None).start(task, "PRIVATE_DRAFT_BODY_FOR_LOCAL_TEST")
            output = StringIO()
            with patch("socket.socket", side_effect=AssertionError("Network forbidden")), \
                    patch("webbrowser.open", side_effect=AssertionError("Browser forbidden")):
                watch_progress(config, store, session.id, output, once=True)
            self.assertIn("승인 대기", output.getvalue())
            self.assertIn("Claude 호출 0회", output.getvalue())
            self.assertNotIn("PRIVATE_", output.getvalue())
            self.assertNotIn("http", output.getvalue())
            self.assertEqual(runner.prompts, [])
            self.assertEqual(store.load(session.id).calls, {})

    def test_completed_session_returns_and_failure_message_stays_in_work_chat(self) -> None:
        config = load_config(ROOT / "orchestrator.toml")
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(config, store, ExternalRunner(), lambda _: None)
            task = parse_task({**public_task(), "allowed_providers": ["claude"]})
            session = bridge.start(task, "Private local display test")
            bridge.decide(session.id, session.checkpoints[-1].id, "approve")
            bridge.review(session.id)
            finished = bridge.finish(session.id, "PRIVATE_FINAL_BODY")
            output = StringIO()
            watch_progress(config, store, session.id, output)
            self.assertIn("완료", output.getvalue())
            self.assertNotIn("PRIVATE_FINAL", output.getvalue())
            finished.status, finished.error = "failed", "PRIVATE_ERROR_BODY"
            store.save(finished)
            failed = StringIO()
            watch_progress(config, store, session.id, failed)
            self.assertIn("실패", failed.getvalue())
            self.assertNotIn("PRIVATE_ERROR", failed.getvalue())

    def test_missing_session_is_visible_without_network_fallback(self) -> None:
        config = load_config(ROOT / "orchestrator.toml")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DoroError):
                watch_progress(config, LocalStore(Path(tmp)), "invalid-id", StringIO(), once=True)

    def test_existing_watch_command_once_works_without_any_cli_on_path(self) -> None:
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
            result = subprocess.run([sys.executable, "-c", code, str(root), "watch", session.id, "--once"],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("승인 대기", result.stdout)
            self.assertNotIn("url", result.stdout)
            self.assertEqual(store.load(session.id).calls, {})
