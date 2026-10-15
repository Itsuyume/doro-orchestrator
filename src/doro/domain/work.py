from doro.domain.models import Config, DoroError, Session, Turn
from doro.domain.policy import ensure_public


def validate_work(config: Config, session: Session) -> None:
    if config.providers["agy"].enabled:
        raise DoroError("AGY must remain disabled in the Work bridge")
    if session.mode != "work" or session.participants != ("work", "claude"):
        raise DoroError("This is not a GPT Work-owned session")
    if session.config_fingerprint != config.fingerprint or session.rounds != config.limits.debate_rounds:
        raise DoroError("Configuration or role instructions changed")
    if session.task.allowed_providers != ("claude",):
        raise DoroError("Work bridge input must explicitly allow only Claude as the external provider")
    if set(session.calls) - {"claude"}:
        raise DoroError("A Work-owned session cannot contain Codex CLI or AGY calls")
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
        if turn.provider == "claude" and previous.provider == "work":
            expected = "review" if reviews == 0 else "recheck"
            if turn.phase != expected or (not session.retry_until_quota and reviews >= session.rounds):
                raise DoroError("Unexpected Claude phase or review limit exceeded")
            reviews += 1
            continue
        if turn.provider != "work" or previous.provider != "claude":
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
