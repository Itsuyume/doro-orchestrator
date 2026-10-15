from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from doro.domain.model_selection import selected_config
from doro.domain.models import DoroError, Reply
from doro.infrastructure.model_settings import ModelSettings, SelectedClaudeRunner
from doro.infrastructure.providers import build_command
import test_native_inputs as inputs_fixture


class ModelSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = inputs_fixture.NativeInputTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.settings = ModelSettings(self.fixture.sessions)

    def test_default_session_isolation_and_ui_token_boundary_without_model_call(self) -> None:
        f = self.fixture
        self.settings.save("claude-opus-5-5", "medium")
        self.assertEqual(self.settings.choice(f.config, f.session.id), ("claude-opus-5-5", "medium"))
        self.settings.save("claude-sonnet-5-5", "high", f.session.id, ui_token=f.token)
        self.assertEqual(self.settings.choice(f.config, f.session.id), ("claude-sonnet-5-5", "high"))
        self.assertEqual(self.settings.choice(f.config, str(uuid4())), ("claude-opus-5-5", "medium"))
        for model, effort, token in [("made-up", "medium", f.token), ("claude-opus-5-5", "bad", f.token),
                                     ("claude-opus-5-5", "medium", "wrong")]:
            with self.assertRaises(DoroError):
                self.settings.save(model, effort, f.session.id, ui_token=token)
        self.assertEqual(self.settings.choice(f.config, f.session.id), ("claude-sonnet-5-5", "high"))
        self.assertEqual(f.runner.prompts, [])
        self.assertEqual(f.sessions.load(f.session.id).status, "awaiting_approval")

    def test_next_call_uses_pinned_model_without_changing_permissions_or_approvals(self) -> None:
        f = self.fixture
        self.settings.save("claude-opus-5-5", "medium")
        resolved = selected_config(f.config, *self.settings.choice(f.config, f.session.id))
        command = build_command(resolved, "claude")
        self.assertEqual(command[command.index("--model") + 1], "claude-opus-5-5")
        self.assertEqual(command[command.index("--effort") + 1], "medium")
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(resolved.fingerprint, f.config.fingerprint)
        self.assertEqual(resolved.providers["agy"], f.config.providers["agy"])
        runner = SelectedClaudeRunner(f.config, self.settings, f.session.id)
        reply = Reply("public review", 3, 0.01, "native", "claude-opus-5-5")
        with patch("doro.infrastructure.model_settings.CliRunner.call", return_value=reply):
            self.assertEqual(runner.call("claude", "public", Path("."), 1).model, reply.model)
        with patch("doro.infrastructure.model_settings.CliRunner.call", return_value=Reply("review", 1, 0.01, "n", "other")):
            with self.assertRaisesRegex(DoroError, "actual other"):
                runner.call("claude", "public", Path("."), 1)
