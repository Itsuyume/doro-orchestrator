from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from doro.application.approval_relay import ApprovalRelay, relay_message
from doro.domain.activity import activity_title
from doro.domain.models import ApprovalReceipt, Config
from doro.infrastructure.storage import LocalStore
from doro.interface.input import read_bounded


def add_approval_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    approvals = commands.add_parser("approvals", help="Local replies from the pet/Work to a registered owning chat")
    actions = approvals.add_subparsers(dest="approval_action", required=True)
    for name in ("pending", "sessions", "outbox"):
        actions.add_parser(name)
    respond = actions.add_parser("respond", help="Record an actual human reply; does not send a message or call a model")
    respond.add_argument("session_id")
    respond.add_argument("--checkpoint", required=True)
    respond.add_argument("--decision", choices=("approve", "reject"), required=True)
    respond.add_argument("--answer", type=Path, required=True)
    for name in ("receipt", "ack"):
        action = actions.add_parser(name)
        action.add_argument("receipt_id")


def receipt_view(receipt: ApprovalReceipt) -> dict[str, object]:
    return {**asdict(receipt), "message": relay_message(receipt), "model_calls": 0,
            "delivery": "Trusted Work must send only a human-authorized reply, then acknowledge success"}


def run_approvals(args: argparse.Namespace, config: Config, store: LocalStore) -> object:
    relay = ApprovalRelay(config, store)
    if args.approval_action == "pending":
        return relay.pending()
    if args.approval_action == "sessions":
        return [{**asdict(route), "activity_title": activity_title(config, store.load(route.session_id), route.label)}
                for route in store.routes()]
    if args.approval_action == "respond":
        answer = read_bounded(args.answer, 2000)
        return receipt_view(relay.respond(args.session_id, args.checkpoint, args.decision, answer))
    if args.approval_action == "outbox":
        return [receipt_view(receipt) for receipt in store.outbox()]
    if args.approval_action == "receipt":
        return receipt_view(store.receipt(args.receipt_id))
    store.acknowledge(args.receipt_id)
    return {"receipt_id": args.receipt_id, "delivered": True}
