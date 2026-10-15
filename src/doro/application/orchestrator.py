import re
import time
from typing import Callable

from doro.application.ports import Runner, Store
from doro.application.prompts import build_prompt
from doro.domain.models import Config, DoroError, PlannedTurn, Session, Turn
from doro.domain.policy import SENSITIVE, allow_call, ensure_public, plan_turns


def public_error(error: BaseException) -> str:
    text = str(error)
    for pattern in SENSITIVE:
        text = re.sub(pattern, "[redacted]", text)
    return text[:2000]


def validate_session(config: Config, session: Session) -> tuple[PlannedTurn, ...]:
    if session.config_fingerprint != config.fingerprint:
        raise DoroError("Configuration changed; existing session cannot silently change roles or limits")
    if session.participants != config.participants() or session.rounds != config.limits.debate_rounds:
        raise DoroError("Stored session plan differs from config")
    if set(session.calls) - set(session.participants):
        raise DoroError("Stored calls contain a nonparticipant")
    plan = plan_turns(session.participants, session.rounds)
    if len(session.turns) > len(plan):
        raise DoroError("Stored turn count exceeds plan")
    for previous, planned in zip(session.turns, plan, strict=False):
        if (previous.provider, previous.phase) != (planned.provider, planned.phase):
            raise DoroError("Stored transcript is out of order")
        ensure_public(previous.text)
    ensure_public(session.task.message + "\n" + session.task.context)
    if not set(session.participants).issubset(session.task.allowed_providers):
        raise DoroError("Task has not explicitly allowed every active provider")
    return plan


class Orchestrator:
    def __init__(self, config: Config, store: Store, runner: Runner,
                 notify: Callable[[str], None]) -> None:
        self.config = config
        self.store = store
        self.runner = runner
        self.notify = notify

    def perform(self, session: Session, turn: PlannedTurn) -> None:
        allow_call(self.config, session, turn.provider)
        prompt = build_prompt(session, turn, self.config.roles[turn.provider], self.config.limits.max_prompt_chars)
        self.store.reserve(session, self.config, turn.provider)
        self.notify(f"{session.id}: {turn.provider} / {turn.phase}")
        timeout = min(self.config.limits.timeout_seconds,
                      self.config.limits.session_seconds - session.seconds_used)
        started = time.monotonic()
        try:
            reply = self.runner.call(turn.provider, prompt, self.store.workspace(session.id), timeout)
            session.tokens_used += reply.tokens
            if reply.cost_usd is not None:
                session.reported_usd += reply.cost_usd
            if session.tokens_used > self.config.limits.max_tokens:
                raise DoroError("Reported token limit exceeded; stop before forwarding")
            if session.reported_usd > self.config.limits.session_reported_usd:
                raise DoroError("Reported cost limit exceeded; stop before forwarding")
            if len(reply.text) > self.config.limits.max_response_chars:
                raise DoroError("Response limit exceeded; nothing was truncated or forwarded")
            ensure_public(reply.text)
            session.turns.append(Turn(turn.provider, turn.phase, reply.text, reply.tokens,
                                      reply.cost_usd, reply.native_session_id))
        finally:
            session.seconds_used += time.monotonic() - started
            self.store.save(session)

    def run(self, session: Session) -> Session:
        with self.store.lock(session.id):
            session = self.store.load(session.id)  # Load under the lock to avoid stale concurrent resumes.
            try:
                plan = validate_session(self.config, session)
                for turn in plan[len(session.turns):]:
                    self.perform(session, turn)
                session.status = "completed"
                session.error = ""
                self.store.save(session)
                self.store.export(session)
                return session
            except KeyboardInterrupt:
                session.status = "interrupted"
                session.error = "Interrupted by user; no automatic retry"
                self.store.save(session)
                raise
            except (DoroError, OSError, ValueError) as error:
                session.status = "failed"
                session.error = public_error(error)
                self.store.save(session)
                raise DoroError(session.error) from error
