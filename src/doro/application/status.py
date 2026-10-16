from doro.application.failures import public_error
from doro.application.prompts import build_prompt
from doro.domain.activity import activity_title
from doro.domain.models import Config, DoroError, PlannedTurn, Session
from doro.domain.progress import progress
from doro.domain.work import review_count
from doro.domain.work_recovery import session_digest


def status_view(config: Config, session: Session) -> dict[str, object]:
    state = progress(config, session)
    state.update({"pending_input": "", "pending_input_error": "", "activity_title": activity_title(config, session)})
    state.update({"session_sha256": session_digest(session),
                  "configuration_matches": session.config_fingerprint == config.fingerprint,
                  "stored_fingerprint": session.config_fingerprint, "current_fingerprint": config.fingerprint,
                  "configuration_recoveries": len(session.recoveries)})
    if session.mode != "work" or session.status in {"running", "completed", "cancelled"} or session.turns[-1].provider != "work":
        return state
    phase = "review" if review_count(session) == 0 else "recheck"
    try:
        state["pending_input"] = build_prompt(session, PlannedTurn("claude", phase),
                                              config.roles["claude"], config.limits.max_prompt_chars)
    except DoroError as error:
        state["pending_input_error"] = public_error(error)
    return state
