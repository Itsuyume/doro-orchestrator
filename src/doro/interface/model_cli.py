import argparse
from pathlib import Path

from doro.domain.model_selection import EFFORTS, MODELS
from doro.infrastructure.model_settings import ModelSettings
from doro.infrastructure.storage import LocalStore


def add_model_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    choice = commands.add_parser("model", help="Set Claude's next-call choice locally; never calls a model")
    choice.add_argument("--session", default="*", help="Exact collaboration UUID; omit for new/default choices")
    choice.add_argument("--model", choices=dict(MODELS), required=True)
    choice.add_argument("--effort", choices=dict(EFFORTS), required=True)


def run_model(args: argparse.Namespace, root: Path) -> dict[str, object]:
    ModelSettings(LocalStore(root / ".doro")).save(args.model, args.effort, args.session)
    return {"model": args.model, "effort": args.effort, "scope": args.session, "applies": "next_review", "model_calls": 0}
