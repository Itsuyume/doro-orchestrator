from dataclasses import dataclass
from collections.abc import Callable
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time

from doro.domain.models import DoroError

SAFE_ENV = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
            "USER", "LOGNAME", "SHELL", "SYSTEMROOT")


@dataclass(frozen=True)
class ProcessResult:
    stdout: str
    stderr: str
    returncode: int


def signal_group(pid: int, kind: signal.Signals) -> bool:
    try:
        os.killpg(pid, kind)
    except ProcessLookupError:
        return False  # The isolated process group has already exited.
    return True


def terminate(process: subprocess.Popen[bytes]) -> None:
    signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=0.3)
    except subprocess.TimeoutExpired:
        signal_group(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
    signal_group(process.pid, signal.SIGKILL)  # Include any still-running descendants.


def read_chunk(selector: selectors.BaseSelector, key: selectors.SelectorKey,
               chunks: dict[str, bytearray], total: int, bound: int,
               on_stdout: Callable[[bytes], None] | None) -> int:
    data = os.read(key.fd, 65536)
    if not data:
        selector.unregister(key.fileobj)
        return total
    total += len(data)
    if total > bound:
        raise DoroError("CLI output exceeded byte limit; process group terminated")
    chunks[str(key.data)].extend(data)
    if key.data == "stdout" and on_stdout is not None:
        on_stdout(data)
    return total


def collect(process: subprocess.Popen[bytes], timeout: float, bound: int,
            on_stdout: Callable[[bytes], None] | None) -> ProcessResult:
    assert process.stdout is not None and process.stderr is not None
    chunks: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    total = 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise DoroError("CLI timed out; isolated process group terminated")
            for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                total = read_chunk(selector, key, chunks, total, bound, on_stdout)
    remaining = max(0.01, deadline - time.monotonic())
    try:
        code = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        raise DoroError("CLI did not exit before its deadline") from error
    return ProcessResult(chunks["stdout"].decode("utf-8"),
                         chunks["stderr"].decode("utf-8"), code)


def run_process(argv: list[str], cwd: Path, env: dict[str, str], incoming: int,
                timeout: float, bound: int, on_stdout: Callable[[bytes], None] | None) -> ProcessResult:
    try:
        with subprocess.Popen(argv, cwd=cwd, env=env, stdin=incoming,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              start_new_session=True) as process:
            try:
                return collect(process, timeout, bound, on_stdout)
            finally:
                terminate(process)
    except OSError as error:
        raise DoroError(f"Unable to start CLI: {error.strerror}") from error


def execute(argv: list[str], prompt: str, cwd: Path, timeout: float, bound: int,
            on_stdout: Callable[[bytes], None] | None = None) -> ProcessResult:
    env = {key: os.environ[key] for key in SAFE_ENV if key in os.environ}
    env.update({"NO_COLOR": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_DISABLE_AUTO_UPDATE": "1", "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
                "AGY_CLI_DISABLE_AUTO_UPDATE": "true"})
    with tempfile.TemporaryFile() as incoming:
        incoming.write(prompt.encode())
        incoming.seek(0)
        return run_process(argv, cwd, env, incoming.fileno(), timeout, bound, on_stdout)
