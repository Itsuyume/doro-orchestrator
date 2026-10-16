import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import unittest

from doro.domain.models import DoroError
from doro.infrastructure.viewer_instance import instance_owner, viewer_locks

ROOT = Path(__file__).resolve().parents[1]
CONCURRENT = """
from pathlib import Path
import subprocess,sys,time
from doro.infrastructure.viewer_instance import instance_owner,viewer_locks
runtime=Path(sys.argv[1])
while not (runtime/'go').exists(): time.sleep(.01)
child=None
with viewer_locks(runtime) as lock:
    instance_owner(runtime,Path('/public-project'),Path('/public-project/config'),claim=lock is not None)
    if lock is not None:
        child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.buffer.read()'],
                               stdin=subprocess.PIPE,pass_fds=(lock,))
print('new' if child else 'reused',flush=True)
if child:
    sys.stdin.buffer.read()
    child.communicate(timeout=5)
"""


class ViewerInstanceTests(unittest.TestCase):
    def test_simultaneous_launches_have_one_owner_and_exit_releases_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            processes = [subprocess.Popen([sys.executable, "-c", CONCURRENT, tmp], env=environment,
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                         for _ in range(12)]
            try:
                (directory / "go").touch()
                responses = self.responses(processes)
                self.assertEqual(responses.count(b"new\n"), 1)
                self.assertEqual(responses.count(b"reused\n"), 11)
                inode = (directory / "viewer.lock").stat().st_ino
                with viewer_locks(directory) as occupied:
                    self.assertIsNone(occupied)
                for process in processes:
                    _, error = process.communicate(timeout=5)
                    self.assertEqual((process.returncode, error), (0, b""))
                with viewer_locks(directory) as available:
                    self.assertIsNotNone(available)
                self.assertEqual((directory / "viewer.lock").stat().st_ino, inode)
                self.assertEqual((directory / "owner.json").stat().st_mode & 0o777, 0o600)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=5)

    def responses(self, processes: list[subprocess.Popen[bytes]]) -> list[bytes]:
        rows: list[bytes] = []
        deadline = time.monotonic() + 10
        with selectors.DefaultSelector() as selector:
            for process in processes:
                assert process.stdout is not None
                selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map() and time.monotonic() < deadline:
                for key, _ in selector.select(0.1):
                    rows.append(os.read(key.fd, 200))
                    selector.unregister(key.fileobj)
        self.assertEqual(len(rows), len(processes), "Concurrent launch requests must finish")
        return rows

    def test_other_project_is_refused_without_changing_owner_or_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            first, other = runtime / "first", runtime / "other"
            with viewer_locks(runtime):
                instance_owner(runtime, first, first / "config", claim=True)
                original = (runtime / "owner.json").read_bytes()
                instance_owner(runtime, first, first / "config", claim=False)
                with self.assertRaisesRegex(DoroError, "다른 설치본"):
                    instance_owner(runtime, other, other / "config", claim=False)
                self.assertEqual((runtime / "owner.json").read_bytes(), original)
            with viewer_locks(runtime):
                instance_owner(runtime, other, other / "config", claim=True)
            self.assertEqual(json.loads((runtime / "owner.json").read_text())["project"], str(other.resolve()))

    def test_killed_owner_releases_both_locks_without_deleting_lock_files(self) -> None:
        code = """
from pathlib import Path
import sys
from doro.infrastructure.viewer_instance import viewer_locks
with viewer_locks(Path(sys.argv[1])) as lock:
 print('ready',flush=True)
 sys.stdin.buffer.read()
"""
        with tempfile.TemporaryDirectory() as tmp:
            environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            process = subprocess.Popen([sys.executable, "-c", code, tmp], env=environment,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                assert process.stdout is not None
                self.assertEqual(process.stdout.readline(), b"ready\n")
                inode = (Path(tmp) / "viewer.lock").stat().st_ino
                process.kill()
                process.communicate(timeout=5)
                with viewer_locks(Path(tmp), timeout=0) as available:
                    self.assertIsNotNone(available)
                self.assertEqual((Path(tmp) / "viewer.lock").stat().st_ino, inode)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_symlink_and_busy_request_never_create_another_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            with viewer_locks(runtime):
                with self.assertRaisesRegex(DoroError, "두 번째 창"):
                    with viewer_locks(runtime, timeout=0):
                        self.fail("A busy request cannot enter the launch section")
            target = runtime / "preserve"
            target.write_text("unchanged")
            (runtime / "owner.json").symlink_to(target)
            with self.assertRaisesRegex(DoroError, "symlink"):
                instance_owner(runtime, runtime, runtime / "config", claim=True)
            self.assertEqual(target.read_text(), "unchanged")
