from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from doro.domain.model_selection import AGY_MODELS, EFFORTS, MODELS
from doro.domain.model_preferences import ModelSelection
from doro.domain.models import Config, DoroError
from doro.infrastructure.model_settings import ModelSettings
from doro.infrastructure.storage import LocalStore


def add_model_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    choice = commands.add_parser("model", help="Set Claude's next-call choice locally; never calls a model")
    choice.add_argument("--session", default="*", help="Exact collaboration UUID; omit for new/default choices")
    choice.add_argument("--provider", choices=("claude", "agy"), default="claude")
    choice.add_argument("--show", action="store_true", help="Read local model choices only; no CLI probe or model call")
    enabled = choice.add_mutually_exclusive_group()
    enabled.add_argument("--enable", dest="enabled", action="store_true")
    enabled.add_argument("--disable", dest="enabled", action="store_false")
    choice.set_defaults(enabled=None)
    choice.add_argument("--model", choices=dict((*MODELS, *AGY_MODELS)))
    choice.add_argument("--effort", choices=dict(EFFORTS))


def run_model(args: argparse.Namespace, root: Path, config: Config) -> dict[str, object]:
    settings = ModelSettings(LocalStore(root / ".doro"))
    if args.show:
        if args.model is not None or args.effort is not None or args.enabled is not None:
            raise DoroError("--show cannot change model choices")
        model, effort = settings.choice(config, args.session)
        return {"providers": {"claude": asdict(ModelSelection(model, effort, "", MODELS, EFFORTS)),
                              "agy": asdict(settings.agy_view(args.session))}, "model_calls": 0}
    if args.model is None or args.effort is None:
        raise DoroError("Setting a model requires --model and --effort")
    if args.provider == "agy":
        enabled = settings.agy_choice(args.session)[2] if args.enabled is None else args.enabled
        settings.save_agy(args.model, args.effort, enabled, args.session)
    elif args.enabled is False:
        raise DoroError("Claude must remain enabled")
    else:
        settings.save(args.model, args.effort, args.session)
    return {"model": args.model, "effort": args.effort, "scope": args.session, "applies": "next_review", "model_calls": 0}
