import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from doro.domain.models import DoroError
from doro.infrastructure.agy_public import AgyStreamGuard, check_customizations, run_public, verified_binary
from doro.infrastructure.protocol import parse_agy


class AgyPublicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bin").mkdir()
        (self.root / "agy").mkdir()
        self.binary = self.root / "bin/agy"
        self.binary.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
if 'plugins' in sys.argv:
 print('[]'); raise SystemExit
assert os.getenv('DORO_TEST_SECRET') is None
packet=json.loads(sys.stdin.readline())
assert packet['message']['content']=='Public review only'
files=sorted(str(p.relative_to(Path.cwd())) for p in Path.cwd().rglob('*') if p.is_file())
assert files==['.agents/agents/doro-public-review.md']
print(json.dumps({'event':'init','init':{'model':'gemini-4-argon-medium','permission_mode':'request-review'}}))
print(json.dumps({'event':'result','result':{'status':'SUCCESS','response':'7','conversation_id':'fixture','usage':{'total_tokens':3},'workspace_files':files}}))
''')
        self.binary.chmod(0o700)
        self.record()

    def record(self) -> None:
        info = self.binary.stat()
        data = {"version": 1, "boundary_verified": True, "binary_size": info.st_size,
                "binary_mtime_ns": info.st_mtime_ns, "binary_sha512": hashlib.sha512(self.binary.read_bytes()).hexdigest()}
        (self.root / "agy/verification.json").write_text(json.dumps(data))

    def test_fresh_workspace_public_packet_and_shared_process_environment(self) -> None:
        original = self.root / "private-note"
        original.write_text("SYNTHETIC_PRIVATE_MARKER")
        os.environ["DORO_TEST_SECRET"] = "DO_NOT_INHERIT"
        try:
            result = run_public([str(self.binary), "--model", "gemini-4-argon-medium"], "Public review only",
                                "gemini-4-argon-medium", self.root, 5, 10000)
        finally:
            del os.environ["DORO_TEST_SECRET"]
        reply = parse_agy(result.stdout)
        self.assertEqual((reply.text, reply.model, reply.tokens), ("7", "gemini-4-argon-medium", 3))
        self.assertEqual(original.read_text(), "SYNTHETIC_PRIVATE_MARKER")
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", result.stdout)
        self.assertEqual(len(list(self.root.iterdir())), 3)

    def test_disabled_or_unverified_binary_and_global_customization_fail_visibly(self) -> None:
        self.binary.write_text(self.binary.read_text() + "\n# changed")
        with self.assertRaises(DoroError):
            verified_binary(self.root, hash_file=True)
        self.record()
        hooks = self.root / ".gemini/config/hooks.json"
        hooks.parent.mkdir(parents=True)
        hooks.write_text("{}")
        with self.assertRaises(DoroError):
            check_customizations(self.root)

    def test_guard_rejects_permission_model_tools_and_missing_init(self) -> None:
        initial = {"event": "init", "init": {"model": "gemini-4-argon-medium", "permission_mode": "request-review"}}
        for key, value in [("model", "other-model"), ("permission_mode", "always-proceed")]:
            packet = {"event": "init", "init": {**initial["init"], key: value}}
            with self.subTest(key=key), self.assertRaises(DoroError):
                AgyStreamGuard("gemini-4-argon-medium").feed((json.dumps(packet) + "\n").encode())
        guard = AgyStreamGuard("gemini-4-argon-medium")
        raw = (json.dumps(initial) + "\n").encode()
        guard.feed(raw[:8])
        guard.feed(raw[8:])
        tool = {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "view_file"}}
        with self.assertRaises(DoroError):
            guard.feed((json.dumps(tool) + "\n").encode())
        with self.assertRaises(DoroError):
            AgyStreamGuard("gemini-4-argon-medium").finish()

    def test_unapproved_private_packet_is_rejected_before_process_execution(self) -> None:
        with self.assertRaises(DoroError):
            run_public([str(self.binary)], "api_key=not-for-sharing", "gemini-4-argon-medium",
                       self.root, 5, 10000)

    def test_authentication_failure_reason_is_preserved_without_fake_success(self) -> None:
        data = json.dumps({"event": "result", "result": {"status": "ERROR", "error": "authentication required"}})
        guard = AgyStreamGuard("gemini-4-argon-medium")
        guard.feed(data.encode())
        guard.finish()
        with self.assertRaisesRegex(DoroError, "authentication required"):
            parse_agy(data)

    def test_unknown_events_tools_and_events_after_terminal_are_rejected(self) -> None:
        initial = {"event": "init", "init": {"model": "gemini-4-argon-medium", "permission_mode": "request-review"}}
        terminal = {"event": "result", "result": {"status": "ERROR", "error": "authentication required"}}
        forbidden = [{"event": kind} for kind in (None, [], "permission_request", "tool_call")]
        forbidden += [{"event": "step_update", "step_update": step} for step in (
            {"step_type": "other"}, {"step_type": None}, {"step_type": []},
            {"step_type": "agent_response", "tool_name": "run_command"},
            {"step_type": "tool", "tool_name": "finish", "tool_info": {"name": "run_command"}},
            {"step_type": "checkpoint", "subagent_info": {"subagents": ["other"]}})]
        for packet in forbidden:
            guard = AgyStreamGuard("gemini-4-argon-medium")
            guard.read(json.dumps(initial).encode())
            with self.subTest(packet=packet), self.assertRaises(DoroError):
                guard.read(json.dumps(packet).encode())
        for first in (initial, terminal):
            guard = AgyStreamGuard("gemini-4-argon-medium")
            guard.read(json.dumps(first).encode())
            if first == initial:
                guard.read(json.dumps(terminal).encode())
            with self.assertRaises(DoroError):
                guard.read(json.dumps(initial).encode())

    def test_plugin_preflight_cannot_replace_binary_before_prompt(self) -> None:
        marker = self.root / "prompt-was-sent"
        self.binary.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
if 'plugins' in sys.argv:
 p=Path(__file__); p.write_text(p.read_text()+'\\n# replaced')
 print('[]'); raise SystemExit
Path(sys.argv[1]).touch()
''')
        self.record()
        with self.assertRaises(DoroError):
            run_public([str(self.binary), str(marker)], "Public review only", "gemini-4-argon-medium",
                       self.root, 5, 10000)
        self.assertFalse(marker.exists())

    def test_known_global_settings_and_instructions_fail_closed_without_changes(self) -> None:
        for relative in (".gemini/settings.json", ".gemini/antigravity/GEMINI.md", ".agents/AGENTS.md"):
            with self.subTest(relative=relative):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"hooks":{}}')
                with self.assertRaises(DoroError):
                    check_customizations(self.root)
                self.assertEqual(path.read_text(), '{"hooks":{}}')
                path.unlink()
