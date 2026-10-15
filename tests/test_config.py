from pathlib import Path
import tempfile
import unittest

from doro.domain.models import DoroError
from doro.infrastructure.config import load_config

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_bad_types_zero_limits_and_insufficient_call_plan_are_rejected(self) -> None:
        original = (ROOT / "orchestrator.toml").read_text()
        changes = (("max_calls = 8", "max_calls = 0"),
                   ("max_calls = 8", "max_calls = true"),
                   ("max_calls = 8", "max_calls = 2"),
                   ("claude_call_usd = 0.50", "claude_call_usd = nan"),
                   ("version = 1", "version = 1\nunknown = 2"))
        for before, after in changes:
            with self.subTest(after=after), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.toml"
                path.write_text(original.replace(before, after))
                with self.assertRaises(DoroError):
                    load_config(path, ROOT / "roles")

    def test_role_changes_change_session_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            for name in ("codex", "claude", "agy"):
                (roles / f"{name}.md").write_text("public role " + name)
            first = load_config(ROOT / "orchestrator.toml", roles)
            (roles / "claude.md").write_text("updated public review role")
            second = load_config(ROOT / "orchestrator.toml", roles)
            self.assertNotEqual(first.fingerprint, second.fingerprint)
