import json
from pathlib import Path
import tempfile
import unittest

from tools.install_input_notifications import install


class InputNotificationInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.codex = self.root / ".codex"
        self.codex.mkdir()
        self.bridge = self.root / "skill with spaces" / "bridge.py"
        self.bridge.parent.mkdir()
        self.bridge.write_text("# fixture; never executed\n")
        self.original = {"description": "Keep", "hooks": {"PostToolUse": [{"matcher": "Existing", "hooks": []}],
                                                         "Stop": [{"hooks": []}]}}
        self.path = self.codex / "hooks.json"
        self.path.write_text(json.dumps(self.original))

    def test_preview_is_read_only_and_install_preserves_other_hooks_and_creates_no_trust(self) -> None:
        before = self.path.read_bytes()
        preview = install(self.codex, self.bridge)
        self.assertFalse(preview["installed"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(set(self.codex.iterdir()), {self.path})
        result = install(self.codex, self.bridge, apply=True)
        self.assertTrue(result["installed"])
        after = json.loads(self.path.read_text())
        self.assertEqual(after["description"], self.original["description"])
        self.assertEqual(after["hooks"]["Stop"], self.original["hooks"]["Stop"])
        self.assertEqual(after["hooks"]["PostToolUse"][0], self.original["hooks"]["PostToolUse"][0])
        self.assertEqual(Path(result["backup"]).read_bytes(), before)
        handlers = after["hooks"]["PostToolUse"]
        self.assertEqual(len(handlers), 2)
        self.assertEqual(handlers[-1]["hooks"][0]["timeout"], 2)
        self.assertTrue(handlers[-1]["hooks"][0]["async"])
        guard = after["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(guard), 1)
        self.assertFalse(guard[0]["hooks"][0]["async"])
        self.assertEqual(guard[0], result["guard_handler"])
        installed = self.path.read_bytes()
        self.assertTrue(install(self.codex, self.bridge, apply=True)["installed"])
        self.assertEqual(self.path.read_bytes(), installed)
        self.assertEqual({p.name for p in self.codex.iterdir()}, {"hooks.json", "skill-archives"})

    def test_invalid_existing_configuration_and_different_hook_are_never_overwritten(self) -> None:
        invalid = [[], {"hooks": []}, {"hooks": {"PostToolUse": {}}}, {"hooks": {"UserPromptSubmit": {}}},
                   {"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "old inputs guard-hook"}]}]}},
                   {"hooks": {"PostToolUse": [{"hooks": [{"command": "old inputs notify-hook"}]}]}}]
        for data in invalid:
            self.path.write_text(json.dumps(data))
            before = self.path.read_bytes()
            with self.assertRaises(ValueError):
                install(self.codex, self.bridge, apply=True)
            self.assertEqual(self.path.read_bytes(), before)
        self.path.write_bytes(b"")
        with self.assertRaises(ValueError):
            install(self.codex, self.bridge, apply=True)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_symlink_hook_path_or_bridge_is_refused(self) -> None:
        other = self.root / "other.json"
        other.write_text(json.dumps(self.original))
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaises(ValueError):
            install(self.codex, self.bridge, apply=True)
        self.assertEqual(json.loads(other.read_text()), self.original)
        self.path.unlink()
        self.path.write_text(json.dumps(self.original))
        linked = self.root / "linked.py"
        linked.symlink_to(self.bridge)
        with self.assertRaises(ValueError):
            install(self.codex, linked, apply=True)

    def test_upgrade_preserves_the_exact_installed_notifier_and_existing_prompt_handlers(self) -> None:
        notifier = install(self.codex, self.bridge)["handler"]
        original_prompt = {"hooks": [{"type": "command", "command": "existing prompt hook"}]}
        original = {"hooks": {"PostToolUse": [notifier], "UserPromptSubmit": [original_prompt]}}
        self.path.write_text(json.dumps(original))
        install(self.codex, self.bridge, apply=True)
        after = json.loads(self.path.read_text())
        self.assertEqual(after["hooks"]["PostToolUse"], original["hooks"]["PostToolUse"])
        self.assertEqual(after["hooks"]["UserPromptSubmit"][0], original_prompt)
        self.assertEqual(len(after["hooks"]["UserPromptSubmit"]), 2)
