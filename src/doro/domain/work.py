from doro.domain.models import Config, DoroError, Session, Turn
from doro.domain.policy import ensure_public


def validate_work(config: Config, session: Session) -> None:
    validate_work_scope(session)
    if session.config_fingerprint != config.fingerprint or session.rounds != config.limits.debate_rounds:
        raise DoroError("Configuration or role instructions changed; inspect work status and use explicit work recover")


def validate_work_scope(session: Session) -> None:
    allowed = set(session.task.allowed_providers)
    expected = ("work", "claude", "agy") if "agy" in allowed else ("work", "claude")
    if session.mode != "work" or session.participants != expected:
        raise DoroError("This is not a GPT Work-owned session")
    if "claude" not in allowed or allowed - {"claude", "agy"}:
        raise DoroError("Work bridge input must explicitly allow its external advisors")
    if set(session.calls) - allowed or any(turn.provider not in {*allowed, "work"} for turn in session.turns):
        raise DoroError("A Work-owned session cannot contain an unapproved advisor or Codex CLI call")
    if session.task.classification != "public":
        raise DoroError("Only explicitly classified public Work input may be shared")
    ensure_public(session.task.message + "\n" + session.task.context)
    validate_work_history(session)


def validate_work_history(session: Session) -> None:
    if not session.turns or (session.turns[0].provider, session.turns[0].phase) != ("work", "draft"):
        raise DoroError("Work session needs its current chat's explicit draft")
    revisions = validate_revisions(session)
    reviews = 0
    for index, turn in enumerate(session.turns):
        ensure_public(turn.text)
        if index == 0:
            continue
        previous = session.turns[index - 1]
        if turn.provider == "work" and turn.phase == "revision" and index in revisions:
            if previous.provider != "work":
                raise DoroError("A recovered draft must follow its preserved Work draft")
            continue
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


def validate_revisions(session: Session) -> set[int]:
    indices: set[int] = set()
    previous = ""
    for recovery in session.recoveries:
        index = recovery.turn_index
        if index in indices or not 0 < index < len(session.turns) or (indices and index <= max(indices)):
            raise DoroError("Invalid recovery revision index; history was not discarded")
        if previous and recovery.previous_fingerprint != previous:
            raise DoroError("Recovery configuration history does not join")
        if (session.turns[index].provider, session.turns[index].phase) != ("work", "revision"):
            raise DoroError("Recovery record has no matching preserved draft revision")
        if recovery.previous_task.allowed_providers != session.task.allowed_providers:
            raise DoroError("Recovered input cannot change approved advisors")
        if recovery.previous_task.classification != "public" or not recovery.reason.strip():
            raise DoroError("Invalid recovered public scope")
        ensure_public(recovery.reason + recovery.previous_task.message + recovery.previous_task.context)
        indices.add(index)
        previous = recovery.fingerprint
    if previous and previous != session.config_fingerprint:
        raise DoroError("Current configuration differs from the last explicit recovery")
    return indices


def work_text(config: Config, text: str, phase: str) -> Turn:
    if not text.strip() or len(text) > config.limits.max_response_chars:
        raise DoroError("Work text must be non-empty and within the response bound")
    ensure_public(text)
    return Turn("work", phase, text, 0, None, "")


def review_count(session: Session) -> int:
    return sum(turn.provider == "claude" for turn in session.turns)
