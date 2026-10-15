from dataclasses import dataclass
from enum import Enum

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


class QueueFailure(DoroError):
    def __init__(self, message: str, uncertain: bool) -> None:
        super().__init__(message)
        self.uncertain = uncertain
