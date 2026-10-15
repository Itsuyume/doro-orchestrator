from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.work_bridge import WorkBridge
from doro.domain.models import DoroError, OwnerRoute
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.pet_swap import PetSwapLedger
from doro.infrastructure.storage import LocalStore
from test_orchestration import ExternalRunner
from test_policy import public_task

ROOT = Path(__file__).resolve().parents[1]


class PetSwapTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = LocalStore(Path(tmp.name))
        self.runner = ExternalRunner()
        bridge = WorkBridge(load_config(ROOT / "orchestrator.toml"), self.store, self.runner, lambda _: None)
        task = parse_task({**public_task(), "allowed_providers": ["claude"]})
        self.a, self.b = bridge.start(task, "Draft A"), bridge.start(task, "Draft B")
        self.owner = str(uuid4())
        for session in (self.a, self.b):
            self.store.bind(OwnerRoute(session.id, self.owner, "Display lease"))
        self.ledger = PetSwapLedger(self.store)

    def test_unknown_off_original_and_wrong_owner_cannot_create_a_restore_target(self) -> None:
        for observed, owner in [("default", self.owner), ("", self.owner), ("pet-original", str(uuid4()))]:
            with self.assertRaises(DoroError):
                self.ledger.change("prepare", self.a.id, owner, observed)
        self.assertIsNone(self.ledger.current())
        self.assertEqual(self.runner.prompts, [])

    def test_only_last_session_requests_restore_and_original_selection_is_preserved(self) -> None:
        self.ledger.change("prepare", self.a.id, self.owner, "pet-original")
        with self.assertRaises(DoroError):
            self.ledger.change("active", self.a.id, self.owner, "pet-original")
        self.ledger.change("active", self.a.id, self.owner, "default")
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.ledger.change("prepare", self.b.id, self.owner, "default"), range(2)))
        self.assertEqual(len(self.ledger.current().sessions), 2)
        first = self.ledger.change("release", self.a.id, self.owner)
        self.assertEqual(first.stage, "active")
        with self.assertRaises(DoroError):
            self.ledger.change("restored", observed="pet-original")
        last = self.ledger.change("release", self.b.id, self.owner)
        self.assertEqual(last.stage, "restoring")
        with self.assertRaises(DoroError):
            self.ledger.change("restored", observed="default")
        final = self.ledger.change("restored", observed="pet-original")
        self.assertEqual((final.stage, final.original_pet_id, final.sessions), ("restored", "pet-original", ()))
        self.assertEqual(self.runner.prompts, [])

    def test_user_changed_pet_is_never_overwritten_or_claimed_as_original_restore(self) -> None:
        self.ledger.change("prepare", self.a.id, self.owner, "pet-original")
        self.ledger.change("active", self.a.id, self.owner, "default")
        with self.assertRaises(DoroError):
            self.ledger.change("prepare", self.b.id, self.owner, "pet-user-changed")
        self.assertEqual(self.ledger.current().original_pet_id, "pet-original")
        self.ledger.change("release", self.a.id, self.owner)
        result = self.ledger.change("restored", observed="pet-user-changed")
        self.assertEqual(result.stage, "superseded")
        self.assertEqual(self.runner.prompts, [])

    def test_failed_preparation_releases_its_lease_without_claiming_a_selection_change(self) -> None:
        self.ledger.change("prepare", self.a.id, self.owner, "pet-original")
        self.ledger.change("prepare", self.b.id, self.owner, "pet-original")
        first = self.ledger.change("release", self.a.id, self.owner)
        self.assertEqual((first.stage, first.sessions), ("prepared", (self.b.id,)))
        last = self.ledger.change("release", self.b.id, self.owner)
        self.assertEqual((last.stage, last.sessions), ("restoring", ()))
        restored = self.ledger.change("restored", observed="pet-original")
        self.assertEqual(restored.stage, "restored")
        self.assertEqual(self.runner.prompts, [])
