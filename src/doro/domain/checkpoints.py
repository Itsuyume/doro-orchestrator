from uuid import uuid4

from doro.domain.models import Checkpoint, Config, DoroError, Session
from doro.domain.policy import ensure_public


def require_approval(session: Session) -> None:
    if session.status in {"awaiting_approval", "awaiting_direction"}:
        raise DoroError("User approval/direction is required; no CLI was started")
    if not any(gate.kind == "start" and gate.decision == "approve" for gate in session.checkpoints):
        raise DoroError("Explicit start-scope approval is required for this Work session")


def request_checkpoint(session: Session, kind: str, summary: str) -> None:
    if kind not in {"start", "branch", "apply"} or not summary.strip() or len(summary) > 6000:
        raise DoroError("Checkpoint needs a valid kind and a non-empty summary within 6000 characters")
    ensure_public(summary)
    if session.status in {"running", "awaiting_approval"}:
        raise DoroError("Cannot replace a running turn or an unanswered approval")
    if session.status == "completed" and kind != "apply":
        raise DoroError("Completed collaboration can only request approval to apply its result")
    if kind != "start" and not any(g.kind == "start" and g.decision == "approve" for g in session.checkpoints):
        raise DoroError("Approve the initial scope before requesting another checkpoint")
    resume = session.status
    if session.status == "awaiting_direction":
        previous = session.checkpoints[-1]
        if previous.kind != kind:
            raise DoroError("Revise the declined checkpoint before continuing")
        resume = previous.resume_status
    session.checkpoints.append(Checkpoint(str(uuid4()), kind, summary, resume))
    session.status = "awaiting_approval"


def decide_checkpoint(session: Session, checkpoint_id: str, decision: str) -> None:
    if session.status != "awaiting_approval" or not session.checkpoints:
        raise DoroError("No unanswered approval exists")
    gate = session.checkpoints[-1]
    if gate.id != checkpoint_id or gate.decision != "pending" or decision not in {"approve", "reject"}:
        raise DoroError("Stale checkpoint or invalid decision; no action was authorized")
    gate.decision = decision
    session.status = gate.resume_status if decision == "approve" else "awaiting_direction"


def start_summary(config: Config, session: Session) -> str:
    return (f"시작 범위: {session.task.message}\n외부 참가자: Claude Code만. AGY는 꺼짐.\n"
            f"최대 검토 {session.rounds}회, 실패 포함 Claude 호출 {config.providers['claude'].max_calls}회, "
            f"호출당 {config.limits.timeout_seconds}초, 예상 비용 예약 상한 "
            f"${config.limits.session_reported_usd:.2f}.\n"
            "아래 공개 입력·초안만 전달. 중요 분기와 실제 파일 반영은 별도 승인. 프로젝트 자동 수정 없음.")
