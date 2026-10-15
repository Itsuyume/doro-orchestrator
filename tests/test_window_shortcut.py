from pathlib import Path
import plistlib
import tempfile
import unittest

from tools.install_window_shortcut import create_app, IDENTITY


class WindowShortcutTests(unittest.TestCase):
    def test_other_application_is_preserved_before_any_build_is_attempted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "Applications/도로협업.app"
            app.mkdir(parents=True)
            marker = app / "keep.txt"
            marker.write_text("preserve")
            with self.assertRaisesRegex(ValueError, "different application"):
                create_app(root, root / "not-a-project")
            self.assertEqual(marker.read_text(), "preserve")
            self.assertFalse((app / "Contents/MacOS").exists())

    def test_existing_binary_symlink_cannot_write_outside_the_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "Applications/도로협업.app"
            binaries = app / "Contents/MacOS"
            binaries.mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": IDENTITY}))
            target = root / "preserve"
            target.write_text("keep")
            (binaries / "DoroOpen").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                create_app(root, root / "not-a-project")
            self.assertEqual(target.read_text(), "keep")
