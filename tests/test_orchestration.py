from dataclasses import replace
from collections.abc import Callable
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from doro.application.orchestrator import Orchestrator
from doro.domain.models import Config, DoroError, Reply, Session
from doro.infrastructure.config import load_config
from doro.infrastructure.providers import build_command
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.diagnostics import probe
from doro.infrastructure.providers import CliRunner
import sys
from test_policy import public_task
from doro.domain.validation import parse_task

ROOT = Path(__file__).resolve().parents[1]


class ExternalRunner:
    """Only the model/provider boundary is simulated; production policy/store run unchanged."""
    def __init__(self, fail_once: bool = False, sensitive: bool = False) -> None:
        self.prompts: list[tuple[str, str]] = []
        self.fail_once = fail_once
        self.sensitive = sensitive

    def call(self, name: str, prompt: str, cwd: Path, timeout: float,
             on_text: Callable[[str], None] | None = None) -> Reply:
        self.prompts.append((name, prompt))
        if self.fail_once and name == "claude":
            self.fail_once = False
            raise DoroError("external authentication failure")
        text = "sk-" + "x" * 30 if self.sensitive else f"{name} public reply {len(self.prompts)}"
        if on_text is not None and name == "claude":
            on_text(text)
        return Reply(text, 20, 0.01 if name == "claude" else None, str(uuid4()))


def new_session(config: Config) -> Session:
    return Session(str(uuid4()), parse_task(public_task()), config.fingerprint,
                   config.participants(), config.limits.debate_rounds)


class OrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "orchestrator.toml")

    def test_bidirectional_history_and_gpt_final_with_no_agy(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp) / "state")
            session = new_session(self.config)
            store.save(session)
            result = Orchestrator(self.config, store, runner, lambda _: None).run(session)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.turns[-1].provider, "codex")
            self.assertEqual(result.calls, {"codex": 3, "claude": 2})
            self.assertEqual(result.tokens_used, 100)
            self.assertIn("codex public reply 1", runner.prompts[1][1])
            self.assertIn("claude public reply 2", runner.prompts[2][1])
            self.assertIn("claude public reply 4", runner.prompts[-1][1])
            self.assertTrue(store.export(result).read_text().endswith(result.turns[-1].text + "\n"))
            self.assertEqual(store.database.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("agy", [name for name, _ in runner.prompts])

    def test_failure_is_visible_and_resume_preserves_cost_and_call_counts(self) -> None:
        runner = ExternalRunner(fail_once=True)
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            session = new_session(self.config)
            store.save(session)
            engine = Orchestrator(self.config, store, runner, lambda _: None)
            with self.assertRaisesRegex(DoroError, "authentication"):
                engine.run(session)
            failed = store.load(session.id)
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.calls, {"codex": 1, "claude": 1})
            self.assertEqual(len(failed.turns), 1)
            finished = engine.run(failed)
            self.assertEqual(finished.calls, {"codex": 3, "claude": 3})
            self.assertEqual(finished.claude_reserved_usd, 1.5)

    def test_sensitive_response_stops_before_next_provider_and_is_not_saved(self) -> None:
        runner = ExternalRunner(sensitive=True)
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            session = new_session(self.config)
            store.save(session)
            with self.assertRaisesRegex(DoroError, "Sensitive"):
                Orchestrator(self.config, store, runner, lambda _: None).run(session)
            result = store.load(session.id)
            self.assertEqual(len(runner.prompts), 1)
            self.assertEqual(result.turns, [])
            self.assertEqual(result.tokens_used, 20)

    def test_daily_limit_is_shared_across_sessions(self) -> None:
        config = replace(self.config, limits=replace(self.config.limits, daily_calls=1))
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            first, second = new_session(config), new_session(config)
            store.save(first)
            store.save(second)
            store.reserve(first, config, "codex")
            with self.assertRaisesRegex(DoroError, "Daily"):
                store.reserve(second, config, "codex")
            self.assertEqual(store.load(second.id).calls, {})

    def test_concurrent_run_is_refused_and_stale_resume_does_not_repeat_turns(self) -> None:
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            session = new_session(self.config)
            store.save(session)
            engine = Orchestrator(self.config, store, runner, lambda _: None)
            with store.lock(session.id), self.assertRaisesRegex(DoroError, "already running"):
                engine.run(session)
            engine.run(session)
            result = engine.run(session)  # Deliberately pass an old in-memory snapshot.
            self.assertEqual(result.status, "completed")
            self.assertEqual(len(runner.prompts), 5)

    def test_disabled_gate_runs_before_cli_lookup_and_config_changes_are_rejected(self) -> None:
        with self.assertRaisesRegex(DoroError, "disabled"):
            build_command(self.config, "agy")
        config = replace(self.config, fingerprint="changed")
        runner = ExternalRunner()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp))
            session = new_session(self.config)
            store.save(session)
            with self.assertRaisesRegex(DoroError, "Configuration changed"):
                Orchestrator(config, store, runner, lambda _: None).run(session)
            self.assertEqual(runner.prompts, [])

    def test_disabled_agy_never_launches_even_an_existing_sentinel_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "agy-was-called"
            script = root / "sentinel.py"
            script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('called')\n")
            agy = replace(self.config.providers["agy"], command=(sys.executable, str(script)))
            config = replace(self.config, providers={**self.config.providers, "agy": agy})
            result = probe(config, "agy", root)
            self.assertEqual(result["checked"], False)
            with self.assertRaisesRegex(DoroError, "disabled"):
                CliRunner(config).call("agy", "public input", root, 5)
            self.assertFalse(marker.exists())

    def test_call_and_usage_limits_prevent_any_further_provider_calls(self) -> None:
        cases = (({"codex": 5}, 0, 0.0), ({}, 100000, 0.0), ({}, 0, 601.0))
        for calls, tokens, seconds in cases:
            with self.subTest(calls=calls, tokens=tokens), tempfile.TemporaryDirectory() as tmp:
                store = LocalStore(Path(tmp))
                session = new_session(self.config)
                session.calls, session.tokens_used, session.seconds_used = calls, tokens, seconds
                store.save(session)
                runner = ExternalRunner()
                with self.assertRaises(DoroError):
                    Orchestrator(self.config, store, runner, lambda _: None).run(session)
                self.assertEqual(runner.prompts, [])
