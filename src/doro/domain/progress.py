from doro.domain.models import Config, Session
from doro.domain.policy import plan_turns
from doro.domain.work import review_count


def progress(config: Config, session: Session) -> dict[str, object]:
    if session.status == "completed":
        speaker, phase = session.turns[-1].provider, "completed"
    elif session.mode == "work":
        speaker = "work" if session.turns[-1].provider == "claude" else "claude"
        phase = "decision" if speaker == "work" else "review" if review_count(session) == 0 else "recheck"
    else:
        plan = plan_turns(session.participants, session.rounds)
        pending = plan[min(len(session.turns), len(plan) - 1)]
        speaker, phase = pending.provider, pending.phase
    return {"session_id": session.id, "mode": session.mode, "status": session.status,
            "speaker": speaker, "phase": phase, "main_owner": "work" if session.mode == "work" else "codex",
            "completed_turns": len(session.turns), "maximum_turns": session.rounds * 2 + 1,
            "calls": session.calls, "call_limit": config.limits.max_calls,
            "claude_call_limit": config.providers["claude"].max_calls,
            "tokens_reported": session.tokens_used, "cost_usd_reported": session.reported_usd,
            "agy_enabled": config.providers["agy"].enabled,
            "error": session.error, "task": session.task.message,
            "turns": [{"speaker": t.provider, "phase": t.phase, "text": t.text} for t in session.turns]}
