import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from doro.domain.models import DoroError
from doro.infrastructure.process import execute


class ProcessTests(unittest.TestCase):
    def test_callback_failure_terminates_the_running_process(self) -> None:
        seen: list[int] = []
        def reject(chunk: bytes) -> None:
            seen.append(int(chunk.strip()))
            raise DoroError("Reject forbidden streaming content")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(DoroError, "forbidden"):
                execute([sys.executable, "-c", "import os,time; print(os.getpid(),flush=True); time.sleep(30)"],
                        "", Path(tmp), 5, 1000, reject)
        self.assertEqual(len(seen), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(seen[0], 0)

    def test_stdout_callback_runs_before_process_completion(self) -> None:
        seen: list[bytes] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "observed"
            code = ("from pathlib import Path; import sys,time; print('streaming',flush=True); "
                    f"p=Path({str(marker)!r}); "
                    "deadline=time.monotonic()+2\n"
                    "while not p.exists() and time.monotonic()<deadline: time.sleep(.01)\n"
                    "sys.exit(0 if p.exists() else 5)")
            def receive(chunk: bytes) -> None:
                seen.append(chunk)
                marker.write_text("received before exit")
            result = execute([sys.executable, "-c", code], "", root, 5, 1000, receive)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b"streaming", b"".join(seen))

    def test_prompt_uses_stdin_and_environment_does_not_forward_secrets(self) -> None:
        code = "import os,sys; print(sys.stdin.read()); print('secret', os.getenv('DORO_TEST_SECRET'))"
        os.environ["DORO_TEST_SECRET"] = "NEVER_FORWARD_THIS"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = execute([sys.executable, "-c", code], "hello", Path(tmp), 5, 1000)
            self.assertIn("hello", result.stdout)
            self.assertIn("secret None", result.stdout)
            self.assertNotIn("NEVER_FORWARD_THIS", result.stdout)
        finally:
            del os.environ["DORO_TEST_SECRET"]

    def test_timeout_and_output_overflow_terminate_process(self) -> None:
        cases = [("import time; time.sleep(30)", 0.15, 1000),
                 ("import sys; sys.stdout.write('x'*10000)", 5, 100)]
        for code, timeout, bound in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(DoroError):
                    execute([sys.executable, "-c", code], "", Path(tmp), timeout, bound)

    def test_nonzero_exit_is_observable_without_swallowing_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = execute([sys.executable, "-c",
                              "import sys; print('explicit failure',file=sys.stderr); sys.exit(7)"],
                             "", Path(tmp), 5, 1000)
        self.assertEqual(result.returncode, 7)
        self.assertIn("explicit failure", result.stderr)

    def test_timeout_stops_descendant_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "descendant-output"
            child = f"import time; from pathlib import Path; time.sleep(0.6); Path({str(marker)!r}).touch()"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
            with self.assertRaises(DoroError):
                execute([sys.executable, "-c", parent], "", Path(tmp), 0.15, 1000)
            time.sleep(0.7)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
