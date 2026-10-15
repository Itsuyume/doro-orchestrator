from dataclasses import asdict
import json

from doro.domain.models import DoroError, Session, Turn
from doro.domain.validation import integer, keys, mapping, number, parse_task, string, strings


def encode_session(session: Session) -> str:
    return json.dumps(asdict(session), ensure_ascii=False, allow_nan=False)


def decode_turn(value: object) -> Turn:
    data = mapping(value, "turn")
    keys(data, set(Turn.__dataclass_fields__), "turn")
    cost = data["cost_usd"]
    return Turn(string(data["provider"], "provider"), string(data["phase"], "phase"),
                string(data["text"], "text"), integer(data["tokens"], "tokens", low=0, high=10_000_000),
                None if cost is None else number(cost, "cost_usd"),
                string(data["native_session_id"], "native_session_id", empty=True))


def decode_session(raw: str) -> Session:
    data = mapping(json.loads(raw), "session")
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
        {k: integer(v, "calls", low=0, high=100) for k, v in calls.items()},
        integer(data["tokens_used"], "tokens_used", low=0, high=100_000_000),
        number(data["reported_usd"], "reported_usd"),
        number(data["claude_reserved_usd"], "claude_reserved_usd"),
        number(data["seconds_used"], "seconds_used"),
        string(data["status"], "status"), string(data["error"], "error", empty=True),
    )
    if session.status not in {"ready", "running", "failed", "interrupted", "completed"}:
        raise DoroError("Invalid stored session status")
    return session
