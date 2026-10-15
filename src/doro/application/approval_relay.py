from uuid import uuid4

from doro.application.ports import RelayStore
from doro.domain.checkpoints import decide_checkpoint
from doro.domain.models import ApprovalReceipt, Config, DoroError, OwnerRoute
from doro.domain.validation import string
from doro.domain.work import validate_work


class ApprovalRelay:
    """Local control records only. The trusted Work host sends an explicitly authorized reply."""
    def __init__(self, config: Config, store: RelayStore) -> None:
        self.config, self.store = config, store

    def pending(self) -> list[dict[str, str]]:
        pending: list[dict[str, str]] = []
        for route in self.store.routes():
            session = self.store.load(route.session_id)
            if session.status != "awaiting_approval":
                continue
            gate = session.checkpoints[-1]
            pending.append({"session_id": session.id, "owner_thread_id": route.thread_id,
                            "label": route.label, "checkpoint_id": gate.id, "kind": gate.kind})
        return pending

    def respond(self, session_id: str, checkpoint_id: str, decision: str, answer: str) -> ApprovalReceipt:
        string(answer, "human answer")
        if len(answer) > 2000:
            raise DoroError("Human control reply exceeds 2000 characters")
        with self.store.lock(session_id):
            session = self.store.load(session_id)
            validate_work(self.config, session)
            routes = {route.session_id: route for route in self.store.routes()}
            if session_id not in routes:
                raise DoroError("No owning Work chat is registered; do not guess a destination")
            route: OwnerRoute = routes[session_id]
            decide_checkpoint(session, checkpoint_id, decision)
            receipt = ApprovalReceipt(str(uuid4()), session.id, checkpoint_id, route.thread_id, decision, answer)
            self.store.record_decision(session, receipt)
            self.store.export(session)
            return receipt


def relay_message(receipt: ApprovalReceipt) -> str:
    return ("사용자가 펫/현재 대화에서 이 도로 협업의 승인 질문에 답해서 전달해.\n"
            f"로컬 응답 기록: {receipt.id}\n세션: {receipt.session_id}\n"
            f"체크포인트: {receipt.checkpoint_id}\n결정: {receipt.decision}\n"
            f"사용자 답변: {receipt.answer}\n"
            "현재 사용자가 이 원래 협업으로 답변 전달을 명시적으로 요청한 경우에만 보낸 메시지야. "
            "로컬 응답 기록과 현재 체크포인트가 일치하는지 확인하고 해당 협업만 이어가. "
            "이미 처리한 기록은 반복 실행하지 마. 보류면 기다려. 새 협업·권한 확대·원문 외부 전달은 하지 마.")
