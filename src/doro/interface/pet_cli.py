from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from doro.infrastructure.pet_swap import PetSwapLedger
from doro.infrastructure.storage import LocalStore


def add_pet_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    swap = commands.add_parser("pet-swap", help="Local display leases only; trusted Work uses official Pets tools")
    actions = swap.add_subparsers(dest="swap_action", required=True)
    actions.add_parser("status")
    for name in ("prepare", "active", "release"):
        action = actions.add_parser(name)
        action.add_argument("session_id")
        action.add_argument("--owner-thread", required=True)
        if name != "release":
            action.add_argument("--observed-pet", required=True, help="Actual active_pet_id from official Pets tool")
    restored = actions.add_parser("restored")
    restored.add_argument("--observed-pet", required=True)


def run_pet_swap(args: argparse.Namespace, root: Path) -> dict[str, object]:
    ledger = PetSwapLedger(LocalStore(root / ".doro"))
    if args.swap_action == "status":
        state = ledger.current()
    elif args.swap_action == "restored":
        state = ledger.change("restored", observed=args.observed_pet)
    else:
        state = ledger.change(args.swap_action, args.session_id, args.owner_thread,
                              args.observed_pet if args.swap_action != "release" else "")
    return {"state": asdict(state) if state else None, "model_calls": 0, "selection_changed": False,
            "restore_needed": state is not None and state.stage == "restoring"}
