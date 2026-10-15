import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys
import tomllib
from uuid import uuid4

from doro.application.orchestrator import Orchestrator, public_error, validate_session
from doro.domain.models import Config, DoroError, Session
from doro.domain.policy import ensure_public, plan_turns
from doro.domain.validation import parse_task
from doro.infrastructure.config import load_config
from doro.infrastructure.diagnostics import doctor, require_auth
from doro.infrastructure.providers import CliRunner
from doro.infrastructure.storage import LocalStore


def parser(root: Path) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="GPT-led public-packet CLI discussion; AGY defaults off")
    result.add_argument("--config", type=Path, default=root / "orchestrator.toml")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Local version/auth checks; never probes disabled participants")
    for name in ("plan", "run"):
        task = commands.add_parser(name)
        task.add_argument("--task", type=Path, required=True)
        if name == "run":
            task.add_argument("--send", action="store_true", help="Explicitly send the public task to approved providers")
    for name in ("show", "resume"):
        session = commands.add_parser(name)
        session.add_argument("session_id")
        if name == "resume":
            session.add_argument("--send", action="store_true", help="Explicit retry; existing counters remain")
    return result


def output(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def prepare(config: Config, path: Path) -> Session:
    if path.is_symlink() or path.stat().st_size > config.limits.max_prompt_chars * 4:
        raise DoroError("Task must be a regular bounded file, without symlinks")
    task = parse_task(json.loads(path.read_text()))
    session = Session(str(uuid4()), task, config.fingerprint,
                      config.participants(), config.limits.debate_rounds)
    validate_session(config, session)
    return session


def preview(config: Config, session: Session) -> None:
    output({"send": False, "task": session.task.to_dict(),
            "turns": [asdict(turn) for turn in plan_turns(session.participants, session.rounds)],
            "limits": asdict(config.limits), "agy_enabled": config.providers["agy"].enabled,
            "privacy": "Only this public text packet is sent; no repository scanning or attachments",
            "note": "Add --send to run; estimated/reportable costs are not billing guarantees"})


def execute_session(config: Config, store: LocalStore, session: Session) -> None:
    require_auth(config)
    for role in config.roles.values():
        ensure_public(role)
    runner = Orchestrator(config, store, CliRunner(config),
                          lambda text: print(text, file=sys.stderr, flush=True))
    result = runner.run(session)
    final = result.turns[-1]
    output({"session_id": result.id, "status": result.status, "calls": result.calls,
            "tokens_reported": result.tokens_used, "cost_usd_reported": result.reported_usd,
            "codex_usd": "not reported; existing ChatGPT subscription login only",
            "final_owner": final.provider, "final": final.text,
            "transcript": str(store.root / "results" / (result.id + ".md"))})


def dispatch(args: argparse.Namespace, root: Path) -> None:
    config = load_config(args.config, root / "roles")
    if args.command == "doctor":
        output({"providers": doctor(config), "pet_bridge": "not connected",
                "configuration": str(args.config)})
        return
    if args.command in ("plan", "run"):
        session = prepare(config, args.task)
        if args.command == "plan" or not args.send:
            preview(config, session)
            return
        store = LocalStore(root / ".doro")
        store.save(session)
        print("Session: " + session.id, file=sys.stderr, flush=True)
        execute_session(config, store, session)
        return
    store = LocalStore(root / ".doro")
    session = store.load(args.session_id)
    if args.command == "show":
        output(asdict(session))
        return
    if not args.send:
        raise DoroError("Resume requires --send; no automatic model calls were made")
    validate_session(config, session)
    execute_session(config, store, session)


def main(root: Path) -> int:
    args = parser(root).parse_args()
    try:
        dispatch(args, root)
    except KeyboardInterrupt:
        print("Interrupted; no automatic retry. Use show/resume to inspect and continue.", file=sys.stderr)
        return 130
    except (DoroError, OSError, ValueError, tomllib.TOMLDecodeError, sqlite3.Error) as error:
        print("DORO ERROR: " + public_error(error), file=sys.stderr)
        return 1
    return 0
