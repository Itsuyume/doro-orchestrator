from dataclasses import dataclass

from doro.domain.models import DoroError, Session


@dataclass(frozen=True)
class NewTaskRequest:
    id: str
    source_session: str
    broker_thread: str
    text_hash: str
    state: str
    thread_id: str
    session_id: str
    child_input_id: str
    error: str


def validate_chat_session(session: Session) -> None:
    if session.participants != ("work",) or session.calls or session.checkpoints or session.exchanges:
        raise DoroError("Chat-only tasks cannot contain advisor calls or approval grants")
    if any(turn.provider != "work" or turn.phase not in {"progress", "final"} for turn in session.turns):
        raise DoroError("Chat-only tasks can contain only their owning GPT's replies")
