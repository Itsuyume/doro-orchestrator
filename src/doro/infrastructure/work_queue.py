from pathlib import Path
import re
import shutil

from doro.domain.models import DoroError
from doro.domain.work_delivery import QueueFailure
from doro.infrastructure.process import execute
from doro.infrastructure.storage import session_key


class CodexQueue:
    """The official existing-thread queue; never starts a second Codex worker."""
    def __init__(self, cwd: Path, binary: Path | None = None) -> None:
        self.cwd = cwd
        self.binary = binary

    def enqueue(self, owner: str, message: str) -> str:
        session_key(owner)
        binary = str(self.binary) if self.binary is not None else shutil.which("codex")
        if binary is None:
            raise QueueFailure("Codex queue is unavailable; the input remains saved", uncertain=False)
        try:
            result = execute([binary, "queue", "--thread", owner, "--message", message], "", self.cwd, 30, 64000)
        except (DoroError, UnicodeError) as error:
            raise QueueFailure(str(error), uncertain=True) from error
        lines = result.stdout.rstrip().splitlines()
        match = re.fullmatch(r"Queued message ([0-9a-f-]+) for thread ([0-9a-f-]+)\.", lines[-1]) if lines else None
        if result.returncode or match is None or match[2] != owner:
            raise QueueFailure("Work delivery result is uncertain; no automatic resend: " + result.stderr[-500:], uncertain=True)
        try:
            return session_key(match[1])
        except DoroError as error:
            raise QueueFailure("Work returned an invalid queue identifier", uncertain=True) from error
