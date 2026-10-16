from dataclasses import dataclass
from enum import Enum
import json

from doro.domain.models import DoroError

INPUT_NOTICE_PREFIX = "$doro-orchestration\nDORO_INPUT "


class DeliveryState(str, Enum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    QUEUED = "queued"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RECEIVED = "received"
    STALE = "stale"


@dataclass(frozen=True)
class WorkDelivery:
    input_id: str
    state: DeliveryState
    queue_id: str = ""
    error: str = ""


class DeliveryEvent(str, Enum):
    SAVED = "saved_at"
    QUEUED = "queued_at"
    NOTIFIED = "notified_at"
    RECEIVED = "received_at"
    ACKNOWLEDGED = "acknowledged_at"


@dataclass(frozen=True)
class DeliveryTiming:
    saved_at: float | None = None
    queued_at: float | None = None
    notified_at: float | None = None
    received_at: float | None = None
    acknowledged_at: float | None = None


def input_notice(input_id: str, session_id: str, owner_thread_id: str) -> str:
    envelope = {"version": 1, "input_id": input_id, "session_id": session_id,
                "owner_thread_id": owner_thread_id}
    return INPUT_NOTICE_PREFIX + json.dumps(envelope)


def parse_input_notice(prompt: object) -> tuple[str, str, str] | None:
    """Recognize only one exact transport envelope; mixed human instructions pass through."""
    if not isinstance(prompt, str) or len(prompt) > 600 or not prompt.startswith(INPUT_NOTICE_PREFIX):
        return None
    try:
        envelope: object = json.loads(prompt[len(INPUT_NOTICE_PREFIX):])
    except json.JSONDecodeError:
        return None  # This human prompt is outside the narrowly recognized transport format.
    expected = {"version", "input_id", "session_id", "owner_thread_id"}
    if not isinstance(envelope, dict) or set(envelope) != expected:
        return None
    if type(envelope["version"]) is not int or envelope["version"] != 1:
        return None
    note, session, owner = envelope["input_id"], envelope["session_id"], envelope["owner_thread_id"]
    if not isinstance(note, str) or not isinstance(session, str) or not isinstance(owner, str):
        return None
    if input_notice(note, session, owner) != prompt:
        return None
    return note, session, owner


class QueueFailure(DoroError):
    def __init__(self, message: str, uncertain: bool) -> None:
        super().__init__(message)
        self.uncertain = uncertain
