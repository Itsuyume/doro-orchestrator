import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from doro.domain.work_delivery import QueueFailure
from doro.infrastructure.work_queue import CodexQueue


class CodexQueueTests(unittest.TestCase):
    def invoke(self, response: str, code: int = 0) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "codex"
            binary.write_text("#!/bin/sh\nprintf '%s\\n' " + shlex.quote(response) + f"\nexit {code}\n")
            binary.chmod(0o700)
            with patch.dict(os.environ, {"PATH": str(root)}):
                return CodexQueue(root).enqueue(self.owner, "IDs only")

    def setUp(self) -> None:
        self.owner, self.receipt = str(uuid4()), str(uuid4())

    def test_queue_accepts_exact_owner_receipt_after_informational_output(self) -> None:
        result = self.invoke(f"Local startup notice\nQueued message {self.receipt} for thread {self.owner}.")
        self.assertEqual(result, self.receipt)

    def test_wrong_owner_malformed_receipt_and_failure_are_uncertain_without_resend(self) -> None:
        outputs = [f"Queued message {self.receipt} for thread {uuid4()}.",
                   f"Queued message invalid for thread {self.owner}.", ""]
        for output in outputs:
            with self.assertRaises(QueueFailure) as failure:
                self.invoke(output)
            self.assertTrue(failure.exception.uncertain)
        with self.assertRaises(QueueFailure) as failure:
            self.invoke(f"Queued message {self.receipt} for thread {self.owner}.", 1)
        self.assertTrue(failure.exception.uncertain)

    def test_missing_cli_is_a_definite_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PATH": tmp}):
            with self.assertRaises(QueueFailure) as failure:
                CodexQueue(Path(tmp)).enqueue(self.owner, "IDs only")
            self.assertFalse(failure.exception.uncertain)
