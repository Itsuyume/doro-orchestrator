import time
from typing import TextIO

from doro.domain.activity import PHASES, STATES, activity_title
from doro.domain.models import Config, Session
from doro.domain.progress import progress
from doro.infrastructure.storage import LocalStore

def activity_text(config: Config, session: Session) -> str:
    state = progress(config, session)
    status = STATES[session.status]
    phase = PHASES[str(state["phase"])]
    return (f"{activity_title(config, session)} · {status} · {phase}\n"
            f"발언 {len(session.turns)}개 · Claude {session.calls.get('claude', 0)}/{config.providers['claude'].max_calls}회"
            f" · AGY {'활성' if config.providers['agy'].enabled else '꺼짐'}\n"
            "진행·승인은 현재 Work 대화와 앱 펫에서 확인해.\n")


def watch_progress(config: Config, store: LocalStore, session_id: str,
                   output: TextIO, *, once: bool = False) -> None:
    previous = ""
    while True:
        session = store.load(session_id)
        text = activity_text(config, session)
        if text != previous:
            output.write(text)
            output.flush()
            previous = text
        if once or session.status in {"completed", "failed", "interrupted", "awaiting_direction", "cancelled"}:
            return
        time.sleep(1)
