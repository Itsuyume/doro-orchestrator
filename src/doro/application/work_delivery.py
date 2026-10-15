from dataclasses import replace
import json
from typing import Protocol

from doro.domain.models import Conversation, HumanInput
from doro.domain.work_delivery import DeliveryState, QueueFailure, WorkDelivery


class Outbox(Protocol):
    def claim(self, note: HumanInput, retry: bool = False) -> tuple[WorkDelivery, bool]: ...
    def complete(self, note_id: str, state: DeliveryState, queue_id: str = "", error: str = "") -> WorkDelivery: ...


class WorkQueue(Protocol):
    def enqueue(self, owner: str, message: str) -> str: ...


class WorkDispatcher:
    def __init__(self, outbox: Outbox, queue: WorkQueue) -> None:
        self.outbox, self.queue = outbox, queue

    def deliver(self, note: HumanInput, retry: bool = False) -> WorkDelivery:
        delivery, claimed = self.outbox.claim(note, retry)
        if not claimed:
            return delivery
        envelope = {"version": 1, "input_id": note.id, "session_id": note.session_id,
                    "owner_thread_id": note.owner_thread_id}
        message = "$doro-orchestration\nDORO_INPUT " + json.dumps(envelope)
        try:
            queue_id = self.queue.enqueue(note.owner_thread_id, message)
        except QueueFailure as error:
            state = DeliveryState.UNKNOWN if error.uncertain else DeliveryState.FAILED
            return self.outbox.complete(note.id, state, error=str(error))
        return self.outbox.complete(note.id, DeliveryState.QUEUED, queue_id)


DELIVERY_LABELS = {
    DeliveryState.PENDING: "저장됨",
    DeliveryState.DISPATCHING: "전달 확인 필요",
    DeliveryState.QUEUED: "Work 확인 대기",
    DeliveryState.FAILED: "Work 연결 실패",
    DeliveryState.UNKNOWN: "전달 확인 필요",
    DeliveryState.RECEIVED: "도로 확인",
    DeliveryState.STALE: "질문 바뀜 · 새 승인 확인",
}


def apply_deliveries(view: Conversation, deliveries: tuple[WorkDelivery, ...]) -> Conversation:
    states = {item.input_id: item for item in deliveries}
    messages = tuple(replace(message, state=DELIVERY_LABELS[states[message.id].state],
                             retryable=states[message.id].state == DeliveryState.FAILED)
                     if message.from_user and message.id in states else message for message in view.messages)
    return replace(view, messages=messages)
