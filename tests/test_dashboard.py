from functools import partial
from http.client import HTTPConnection
from http.server import HTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest

from doro.application.work_bridge import WorkBridge
from doro.infrastructure.config import load_config
from doro.infrastructure.storage import LocalStore
from doro.interface.dashboard import ProgressHandler
from test_orchestration import ExternalRunner
from test_policy import public_task
from doro.domain.validation import parse_task

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def test_only_selected_session_is_readable_with_local_token(self) -> None:
        config = load_config(ROOT / "orchestrator.toml")
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            bridge = WorkBridge(config, store, ExternalRunner(), lambda _: None)
            task = parse_task({**public_task(), "allowed_providers": ["claude"]})
            session = bridge.start(task, "Public draft <script>alert('text only')</script>")
            handler = partial(ProgressHandler, config=config, store=store, session_id=session.id,
                              token="test-local-token", assets=ROOT / "ui", touched=[time.monotonic()])
            with HTTPServer(("127.0.0.1", 0), handler) as server:
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    self.check_responses(server.server_port, session.id)
                finally:
                    server.shutdown()
                    thread.join(timeout=3)

    def check_responses(self, port: int, expected_id: str) -> None:
        cases = [("/api/status", {}, 401),
                 ("/api/status", {"Authorization": "Bearer test-local-token"}, 200),
                 ("/api/status", {"Authorization": "Bearer test-local-token", "Origin": "https://example.com"}, 403),
                 ("/api/status", {"Authorization": "Bearer test-local-token", "Host": "evil.example"}, 403),
                 ("/../../.doro/sessions.sqlite3", {}, 404),
                 ("/", {}, 200)]
        for path, headers, status in cases:
            with self.subTest(path=path, status=status):
                connection = HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("GET", path, headers=headers)
                result = connection.getresponse()
                body = result.read()
                connection.close()
                self.assertEqual(result.status, status)
                self.assertEqual(result.getheader("Cache-Control"), "no-store")
                if path == "/api/status" and status == 200:
                    state = json.loads(body)
                    self.assertEqual(state["session_id"], expected_id)
                    self.assertEqual(state["calls"], {})
                    self.assertIn("<script>", state["turns"][0]["text"])
