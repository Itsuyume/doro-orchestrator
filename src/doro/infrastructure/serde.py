from dataclasses import asdict
import json

from doro.domain.models import ApprovalReceipt, Checkpoint, DoroError, Exchange, Session, Turn
from doro.domain.validation import boolean, integer, keys, mapping, number, parse_task, string, strings


def encode_session(session: Session) -> str:
    return json.dumps(asdict(session), ensure_ascii=False, allow_nan=False)


def encode_receipt(receipt: ApprovalReceipt) -> str:
    return json.dumps(asdict(receipt), ensure_ascii=False, allow_nan=False)


def decode_receipt(raw: str) -> ApprovalReceipt:
    data = mapping(json.loads(raw), "approval receipt")
    keys(data, set(ApprovalReceipt.__dataclass_fields__), "approval receipt")
    return ApprovalReceipt(string(data["id"], "id"), string(data["session_id"], "session_id"),
                           string(data["checkpoint_id"], "checkpoint_id"),
                           string(data["owner_thread_id"], "owner_thread_id"),
                           string(data["decision"], "decision"), string(data["answer"], "answer"),
                           boolean(data["delivered"], "delivered"))


def decode_turn(value: object) -> Turn:
    data = mapping(value, "turn")
    data.setdefault("model", "")  # Older turns did not retain the provider's model metadata.
    keys(data, set(Turn.__dataclass_fields__), "turn")
    cost = data["cost_usd"]
    return Turn(string(data["provider"], "provider"), string(data["phase"], "phase"),
                string(data["text"], "text"), integer(data["tokens"], "tokens", low=0, high=10_000_000),
                None if cost is None else number(cost, "cost_usd"),
                string(data["native_session_id"], "native_session_id", empty=True),
                string(data["model"], "model", empty=True))


def decode_session(raw: str) -> Session:
    data = mapping(json.loads(raw), "session")
    data.setdefault("retry_until_quota", False)  # v4 records retain the original bounded-call policy.
    data.setdefault("retry_instructions", "")
    missing = set(Session.__dataclass_fields__) - set(data)
    if missing in ({"mode", "checkpoints", "exchanges"}, {"checkpoints", "exchanges"}):
        data.setdefault("mode", "cli")
        data["checkpoints"], data["exchanges"] = [], []  # Explicit v1/v2 record migration; no implicit approval.
    keys(data, set(Session.__dataclass_fields__), "session")
    turns = data["turns"]
    if not isinstance(turns, list):
        raise DoroError("Invalid stored turn list")
    calls = mapping(data["calls"], "calls")
    session = Session(
        string(data["id"], "id"), parse_task(data["task"]),
        string(data["config_fingerprint"], "config_fingerprint"),
        strings(data["participants"], "participants"),
        integer(data["rounds"], "rounds", high=3),
        [decode_turn(turn) for turn in turns],
        {k: integer(v, "calls", low=0, high=2**63 - 1) for k, v in calls.items()},
        integer(data["tokens_used"], "tokens_used", low=0, high=100_000_000),
        number(data["reported_usd"], "reported_usd"),
        number(data["claude_reserved_usd"], "claude_reserved_usd"),
        number(data["seconds_used"], "seconds_used"),
        string(data["status"], "status"), string(data["error"], "error", empty=True),
        string(data["mode"], "mode"),
        [decode_checkpoint(item) for item in record_list(data["checkpoints"], "checkpoints")],
        [decode_exchange(item) for item in record_list(data["exchanges"], "exchanges")],
        boolean(data["retry_until_quota"], "retry_until_quota"),
        string(data["retry_instructions"], "retry_instructions", empty=True),
    )
    if session.mode not in {"cli", "work"}:
        raise DoroError("Invalid stored session mode")
    if session.status not in {"ready", "running", "failed", "interrupted", "completed",
                              "awaiting_claude", "awaiting_work", "awaiting_approval", "awaiting_direction", "cancelled"}:
        raise DoroError("Invalid stored session status")
    if session.status == "awaiting_approval" and (not session.checkpoints or session.checkpoints[-1].decision != "pending"):
        raise DoroError("Invalid stored approval wait: no unanswered checkpoint")
    return session


def record_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise DoroError(f"Invalid stored {name} list")
    return list(value)


def decode_checkpoint(value: object) -> Checkpoint:
    data = mapping(value, "checkpoint")
    data.setdefault("brief", "")  # Legacy detail remains intact, without an invented summary.
    keys(data, set(Checkpoint.__dataclass_fields__), "checkpoint")
    fields = {key: string(value, key, empty=key == "brief") for key, value in data.items()}
    if fields["kind"] not in {"start", "branch", "apply"} or fields["decision"] not in {"pending", "approve", "reject"}:
        raise DoroError("Invalid stored checkpoint")
    return Checkpoint(**fields)


def decode_exchange(value: object) -> Exchange:
    data = mapping(value, "exchange")
    keys(data, set(Exchange.__dataclass_fields__), "exchange")
    fields = {key: string(value, key, empty=key in {"output", "error"}) for key, value in data.items()}
    if fields["status"] not in {"running", "completed", "failed", "interrupted"}:
        raise DoroError("Invalid stored exchange status")
    return Exchange(**fields)
