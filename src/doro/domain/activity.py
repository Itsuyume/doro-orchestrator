from doro.domain.models import Config, Session
from doro.domain.progress import progress

STATES = {"ready": "준비", "running": "진행 중", "awaiting_approval": "승인 대기",
          "awaiting_direction": "방향 결정 대기", "awaiting_claude": "Claude 검토 대기",
          "awaiting_work": "도로 반론·보완 중", "completed": "완료", "failed": "실패", "interrupted": "중단",
          "cancelled": "종료"}
PHASES = {"draft": "초안", "review": "Claude 검토", "rebuttal": "도로 반론·보완",
          "recheck": "Claude 재검토", "final": "도로 최종 판단", "decision": "도로 검토 결과 반영",
          "completed": "도로 최종 판단 완료"}
GATES = {"start": "시작 범위", "branch": "중요 분기", "apply": "파일 반영"}


def activity_title(config: Config, session: Session, label: str = "도로 협업") -> str:
    if session.status == "awaiting_approval":
        return label + " · " + GATES[session.checkpoints[-1].kind] + " 승인 대기"
    if session.status == "running":
        return label + " · " + PHASES[str(progress(config, session)["phase"])] + " 중"
    return label + " · " + STATES[session.status]
