from pathlib import Path
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from doro.domain.model_selection import selected_config
from doro.domain.models import DoroError, Reply
from doro.infrastructure.model_settings import ModelSettings, SelectedAdvisorRunner
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
        self.assertEqual(json.loads(command[command.index("--settings") + 1]),
                         {"disableAllHooks": True, "fallbackModel": [], "availableModels": ["claude-opus-5-5"]})
        self.assertEqual(resolved.fingerprint, f.config.fingerprint)
        self.assertEqual(resolved.providers["agy"], f.config.providers["agy"])
        runner = SelectedAdvisorRunner(f.config, self.settings, f.session.id)
        reply = Reply("public review", 3, 0.01, "native", "claude-opus-5-5")
        with patch("doro.infrastructure.model_settings.CliRunner.call", return_value=reply):
            self.assertEqual(runner.call("claude", "public", Path("."), 1).model, reply.model)
        with patch("doro.infrastructure.model_settings.CliRunner.call", return_value=Reply("review", 1, 0.01, "n", "other")):
            with self.assertRaisesRegex(DoroError, "actual other"):
                runner.call("claude", "public", Path("."), 1)

    def test_agy_preferences_preserve_claude_and_require_ui_capability_without_call(self) -> None:
        f = self.fixture
        self.assertEqual(self.settings.agy_choice(f.session.id), ("gemini-4-argon", "medium", False))
        self.settings.save_agy("gemini-4-argon", "medium", True)
        self.settings.save_agy("gemini-4-argon", "high", False, f.session.id, ui_token=f.token)
        self.assertEqual(self.settings.agy_choice(f.session.id), ("gemini-4-argon", "high", False))
        self.assertEqual(self.settings.agy_choice(str(uuid4())), ("gemini-4-argon", "medium", True))
        with self.assertRaises(DoroError):
            self.settings.save_agy("gemini-4-argon", "medium", True, f.session.id, ui_token="wrong")
        with self.assertRaises(DoroError):
            self.settings.save_agy("gemini-4-argon", "max", True)
        selected = self.settings.work_config(f.config, f.session.id)
        self.assertEqual(selected.fingerprint, f.config.fingerprint)
        self.assertFalse(selected.providers["agy"].enabled)
        self.assertEqual(selected.providers["claude"], f.config.providers["claude"])
        self.assertEqual(f.runner.prompts, [])
