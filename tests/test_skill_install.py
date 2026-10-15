import json
from pathlib import Path
import tempfile
import unittest

from tools.install_work_skill import install

ROOT = Path(__file__).resolve().parents[1]


class SkillInstallTests(unittest.TestCase):
    def test_installed_bridge_is_bound_without_project_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            install(target, ROOT)
            doc = target / ".codex/skill-docs/doro-orchestration.json"
            value = json.loads(doc.read_text())
            self.assertEqual(value["project_root"], str(ROOT))
            self.assertEqual(value["external"], ["claude"])
            self.assertFalse(value["agy_enabled"])
            self.assertEqual(doc.stat().st_mode & 0o777, 0o600)
            self.assertTrue((target / ".codex/skills/doro-orchestration/scripts/bridge.py").is_file())

    def test_local_edits_are_preserved_and_duplicates_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            install(target, ROOT)
            skill = target / ".codex/skills/doro-orchestration/SKILL.md"
            skill.write_text("user local customization")
            with self.assertRaises(SystemExit):
                install(target, ROOT)
            self.assertEqual(skill.read_text(), "user local customization")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / ".agents/skills/doro-orchestration").mkdir(parents=True)
            with self.assertRaises(SystemExit):
                install(target, ROOT)
            self.assertFalse((target / ".codex/skills/doro-orchestration").exists())
