from doro.domain.models import Config, DoroError, Session, Turn
from doro.domain.policy import ensure_public


def validate_work(config: Config, session: Session) -> None:
    allowed = set(session.task.allowed_providers)
    expected = ("work", "claude", "agy") if "agy" in allowed else ("work", "claude")
    if session.mode != "work" or session.participants != expected:
        raise DoroError("This is not a GPT Work-owned session")
    if session.config_fingerprint != config.fingerprint or session.rounds != config.limits.debate_rounds:
        raise DoroError("Configuration or role instructions changed")
    if "claude" not in allowed or allowed - {"claude", "agy"}:
        raise DoroError("Work bridge input must explicitly allow its external advisors")
    if set(session.calls) - allowed or any(turn.provider not in {*allowed, "work"} for turn in session.turns):
        raise DoroError("A Work-owned session cannot contain an unapproved advisor or Codex CLI call")
    ensure_public(session.task.message + "\n" + session.task.context)
    validate_work_history(session)


def validate_work_history(session: Session) -> None:
    if not session.turns or (session.turns[0].provider, session.turns[0].phase) != ("work", "draft"):
        raise DoroError("Work session needs its current chat's explicit draft")
    reviews = 0
    for index, turn in enumerate(session.turns):
        ensure_public(turn.text)
        if index == 0:
            continue
        previous = session.turns[index - 1]
        if turn.provider in {"claude", "agy"} and previous.provider == "work":
            expected = "ideas" if turn.provider == "agy" else "review" if reviews == 0 else "recheck"
            if turn.phase != expected or (not session.retry_until_quota and reviews >= session.rounds):
                raise DoroError("Unexpected Claude phase or review limit exceeded")
            reviews += int(turn.provider == "claude")
            continue
        if turn.provider != "work" or previous.provider not in {"claude", "agy"}:
            raise DoroError("Work/Claude transcript is out of order")
        if turn.phase not in {"rebuttal", "final"} or (turn.phase == "final" and index != len(session.turns) - 1):
            raise DoroError("Invalid Work phase")


def work_text(config: Config, text: str, phase: str) -> Turn:
    if not text.strip() or len(text) > config.limits.max_response_chars:
        raise DoroError("Work text must be non-empty and within the response bound")
    ensure_public(text)
    return Turn("work", phase, text, 0, None, "")


def review_count(session: Session) -> int:
    return sum(turn.provider == "claude" for turn in session.turns)
