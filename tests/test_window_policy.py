import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from doro.domain.models import DoroError
from doro.infrastructure.process import execute
from doro.infrastructure.window_policy import WindowLease, enable, required


class WindowPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.write_owner(self.root)

    def write_owner(self, project: Path) -> None:
        temporary = self.runtime / "owner.new"
        temporary.write_text(json.dumps({"version": 1, "project": str(project.resolve()), "config": "public.toml"}))
        temporary.replace(self.runtime / "owner.json")

    def hold_viewer(self) -> int:
        descriptor = os.open(self.runtime / "viewer.lock", os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor

    def test_off_and_wrong_installation_are_blocked(self) -> None:
        with self.assertRaisesRegex(DoroError, "꺼져"):
            WindowLease(self.root, self.runtime)
        descriptor = self.hold_viewer()
        try:
            with self.assertRaisesRegex(DoroError, "다른 설치본"):
                WindowLease(self.root / "other", self.runtime)
        finally:
            os.close(descriptor)

    def test_hidden_window_keeps_lease_but_exit_and_restart_end_it(self) -> None:
        descriptor = self.hold_viewer()
        lease = WindowLease(self.root, self.runtime)
        self.assertTrue(lease.active())  # Visibility is deliberately not part of the permit.
        self.write_owner(self.root)
        self.assertFalse(lease.active(), "A new window instance cannot revive an old in-flight permit")
        restarted = WindowLease(self.root, self.runtime)
        self.assertTrue(restarted.active())
        os.close(descriptor)
        self.assertFalse(restarted.active())

    def test_policy_is_persistent_private_and_corruption_is_visible(self) -> None:
        state = self.root / "state"
        self.assertFalse(required(state))
        enable(state)
        self.assertTrue(required(state))
        self.assertEqual((state / "window-policy.json").stat().st_mode & 0o777, 0o600)
        (state / "window-policy.json").write_text("broken")
        with self.assertRaises(ValueError):
            required(state)
        self.assertEqual((state / "window-policy.json").read_text(), "broken")

    def test_closed_gate_has_no_process_side_effect(self) -> None:
        marker = self.root / "started"
        code = f"from pathlib import Path; Path({str(marker)!r}).touch()"
        with self.assertRaisesRegex(DoroError, "차단"):
            execute([sys.executable, "-c", code], "", self.root, 5, 1000, keep_running=lambda: False)
        self.assertFalse(marker.exists())

    def test_exit_cancels_even_after_cli_closes_both_pipes(self) -> None:
        descriptor = self.hold_viewer()
        lease = WindowLease(self.root, self.runtime)
        seen: list[int] = []
        code = "import os,time; print(os.getpid(),flush=True); os.close(1); os.close(2); time.sleep(20)"
        timer = threading.Timer(0.4, os.close, args=(descriptor,))
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(DoroError, "종료"):
                execute([sys.executable, "-c", code], "", self.root, 8, 1000,
                        lambda chunk: seen.append(int(chunk.strip())), lease.active)
        finally:
            timer.join()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(seen), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(seen[0], 0)
