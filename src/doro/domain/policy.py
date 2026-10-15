import re

from doro.domain.models import Config, DoroError, PlannedTurn, Session

SENSITIVE = (
    r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[\w]{20,}|AIza[\w-]{20,})",
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----",
    r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|authorization)\s*[:=]\s*\S+",
    r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b",
    r"(?i)(?:/Users/|/home/|[A-Z]:\\Users\\|iCloud~md~obsidian|\.credentials\.json|\.env\b)",
    r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
)


def ensure_public(text: str) -> None:
    if any(re.search(pattern, text) for pattern in SENSITIVE):
        raise DoroError("Sensitive input/output detected; nothing further will be forwarded")


def plan_turns(participants: tuple[str, ...], rounds: int) -> tuple[PlannedTurn, ...]:
    turns = [PlannedTurn("codex", "draft")]
    if "agy" in participants:
        turns.append(PlannedTurn("agy", "ideas"))
    for index in range(rounds):
        if "claude" in participants:
            turns.append(PlannedTurn("claude", "review" if index == 0 else "recheck"))
        if index < rounds - 1:
            turns.append(PlannedTurn("codex", "rebuttal"))
    turns.append(PlannedTurn("codex", "final"))
    return tuple(turns)


def quota_retry(session: Session, provider: str) -> bool:
    return session.mode == "work" and provider == "claude" and session.retry_until_quota


def allow_call(config: Config, session: Session, provider_name: str) -> None:
    provider = config.providers[provider_name]
    if not provider.enabled:
        raise DoroError(f"{provider_name} is disabled; no process was launched")
    if provider_name not in session.task.allowed_providers:
        raise DoroError(f"{provider_name} is not approved for this input")
    if quota_retry(session, provider_name):
        return  # Explicit per-session human override; byte, privacy and per-call time bounds still apply.
    limits = config.limits
    if sum(session.calls.values()) >= limits.max_calls:
        raise DoroError("Session call limit reached")
    if session.calls.get(provider_name, 0) >= provider.max_calls:
        raise DoroError(f"{provider_name} call limit reached")
    if session.tokens_used >= limits.max_tokens:
        raise DoroError("Reported token limit reached")
    if session.seconds_used >= limits.session_seconds:
        raise DoroError("Session active-time limit reached")
    reserved = session.claude_reserved_usd
    if provider_name == "claude":
        reserved += limits.claude_call_usd
    if max(session.reported_usd, reserved) > limits.session_reported_usd:
        raise DoroError("Reported/reserved cost limit reached")
