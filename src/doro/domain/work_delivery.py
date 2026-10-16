from dataclasses import dataclass
from enum import Enum
import json

from doro.domain.models import DoroError


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
    return "$doro-orchestration\nDORO_INPUT " + json.dumps(envelope)


class QueueFailure(DoroError):
    def __init__(self, message: str, uncertain: bool) -> None:
        super().__init__(message)
        self.uncertain = uncertain
