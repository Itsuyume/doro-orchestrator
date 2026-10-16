from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from doro.domain.models import DoroError
from doro.domain.shared_radar import changed_revisions
from doro.domain.work_delivery import QueueFailure
from doro.infrastructure.radar_store import journal
from doro.interface.shared_radar import inspect_once
from radar_fixture import PAGES, calls, fixture


class SharedRadarTests(unittest.TestCase):
    def test_metadata_connection_cleans_its_own_child_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = fixture(root)
            (root / "spawn-child").touch()
            with journal(settings.state_root, settings.owner) as store:
                self.assertEqual(inspect_once(settings, store)["state"], "unchanged")
            child = (root / "child.pid").read_text()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                result = subprocess.run(["ps", "-o", "stat=", "-p", child], capture_output=True, text=True)
                if not result.stdout.strip() or result.stdout.strip().startswith("Z"):
                    break
                time.sleep(0.02)
            else:
                self.fail("Metadata subprocess survived connection cleanup")

    def test_configuration_never_opens_the_protected_vault_from_the_background_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = fixture(root)
            settings.connection.unlink()
            os.mkfifo(settings.connection)
            config = root / "config.json"
            config.write_text(json.dumps({"version": 1, "enabled": True, "connection": str(settings.connection),
                "automation": str(settings.automation), "state_root": str(settings.state_root),
                "codex": str(settings.codex), "obsidian": str(settings.obsidian), "owner": settings.owner,
                "remote_seconds": 1800}))
            code = "from pathlib import Path; from doro.infrastructure.radar_settings import load_settings; import sys; print(load_settings(Path(sys.argv[1])).owner)"
            result = subprocess.run([sys.executable, "-c", code, str(config)], capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), settings.owner)

    def test_empty_unchanged_missing_and_older_baselines(self) -> None:
        self.assertEqual(changed_revisions({}, {}, {}), ())
        self.assertEqual(changed_revisions({"p": 2}, {"p": 2}, {}), ())
        self.assertEqual(changed_revisions({"p": 3}, {"p": 2}, {"n": "a"}), ("outbox:n:a", "page:p:3"))
        for remote, received in [({"p": 1}, {"p": 2}), ({}, {"p": 2})]:
            with self.assertRaises(DoroError):
                changed_revisions(remote, received, {})

    def test_unchanged_uses_metadata_only_and_never_queues_a_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = fixture(root)
            with journal(settings.state_root, settings.owner) as store:
                self.assertEqual(inspect_once(settings, store), {"state": "unchanged", "work_queued": False})
                self.assertEqual(store.status(), {"events": []})
                self.assertEqual(inspect_once(settings, store)["state"], "unchanged")
            trace = calls(root)
            self.assertEqual([x["method"] for x in trace],
                             ["initialize", "initialized", "thread/start", "mcpServer/tool/call", "mcpServer/tool/call"])
            self.assertEqual(trace[2]["params"], {"ephemeral": True})
            for call in trace[3:]:
                self.assertIs(call["params"]["arguments"]["include_content"], False)

    def test_outbox_change_queues_exactly_once_and_never_sends_its_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = fixture(root)
            (root / "probe.json").write_text(json.dumps({"enabled": True, "pending": [{"id": "note", "sha": "a" * 64}]}))
            with patch.dict("os.environ", {"PATH": str(root)}), journal(settings.state_root, settings.owner) as store:
                result = inspect_once(settings, store)
                self.assertEqual(result["state"], "queued")
                self.assertEqual(result["changes"], ["outbox:note:" + "a" * 64])
                self.assertEqual(inspect_once(settings, store)["state"], "unchanged")
            queue = [c for c in calls(root) if c.get("command") == "queue"]
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["args"][1], settings.owner)
            self.assertNotIn("markdown", queue[0]["args"][-1])

    def test_space_change_and_received_copy_do_not_cause_a_return_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = fixture(root)
            versions = {PAGES[0]: 2, PAGES[1]: 1}
            (root / "remote.json").write_text(json.dumps(versions))
            with patch.dict("os.environ", {"PATH": str(root)}), journal(settings.state_root, settings.owner) as store:
                result = inspect_once(settings, store)
                self.assertEqual(result["changes"], ["page:" + PAGES[0] + ":2"])
                state = settings.vault / ".obsidian/plugins/doro-study-sync/shared-state.json"
                state.write_text(json.dumps({"pages": {p: {"sequence": v} for p, v in versions.items()}}))
                self.assertEqual(inspect_once(settings, store)["state"], "unchanged")
            self.assertEqual(sum(c.get("command") == "queue" for c in calls(root)), 1)

    def test_unknown_queue_receipt_is_preserved_and_not_automatically_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = fixture(root)
            (root / "bad-queue").touch()
            (root / "probe.json").write_text(json.dumps({"enabled": True, "pending": [{"id": "note", "sha": "b" * 64}]}))
            with patch.dict("os.environ", {"PATH": str(root)}), journal(settings.state_root, settings.owner) as store:
                with self.assertRaises(QueueFailure):
                    inspect_once(settings, store)
                self.assertEqual(store.status()["events"][0]["state"], "unknown")
                self.assertEqual(inspect_once(settings, store)["state"], "unchanged")
            self.assertEqual(sum(c.get("command") == "queue" for c in calls(root)), 1)

    def test_pause_and_disabled_settings_do_not_call_space_or_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = fixture(root)
            with journal(settings.state_root, settings.owner) as store:
                self.assertEqual(inspect_once(replace(settings, enabled=False), store)["state"], "disabled")
                (root / "probe.json").write_text('{"enabled":false,"pending":[]}')
                self.assertEqual(inspect_once(settings, store)["state"], "obsidian_paused")
            self.assertEqual(calls(root), [])

    def test_invalid_remote_response_and_missing_receipts_never_queue(self) -> None:
        for invalid in [None, -1, True, "2"]:
            with self.subTest(sequence=invalid), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                settings = fixture(root)
                (root / "remote.json").write_text(json.dumps({p: invalid for p in PAGES}))
                with journal(settings.state_root, settings.owner) as store, self.assertRaises(DoroError):
                    inspect_once(settings, store)
                self.assertFalse(any(c.get("command") == "queue" for c in calls(root)))

    def test_delivery_reservation_survives_restart_and_rejects_overlapping_inspections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, owner = Path(tmp), "owner"
            with journal(root, owner) as store:
                claim = store.claim(("page:p:2",))
                self.assertIsNotNone(claim)
                with self.assertRaises(DoroError), journal(root, owner):
                    pass
            with journal(root, owner) as store:
                self.assertIsNone(store.claim(("page:p:2",)))
                self.assertEqual(store.status()["events"][0]["state"], "dispatching")
            with self.assertRaises(DoroError), journal(root, "another-owner"):
                pass
