from typing import Callable

from doro.application.failures import public_error
from doro.application.ports import Runner, Store
from doro.application.turn_executor import TurnExecutor
from doro.domain.models import Config, DoroError, PlannedTurn, Session
from doro.domain.policy import ensure_public, plan_turns


def validate_session(config: Config, session: Session) -> tuple[PlannedTurn, ...]:
    if session.mode != "cli":
        raise DoroError("This session belongs to the current GPT Work chat; use work commands")
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
        self.executor = TurnExecutor(config, store, runner, notify)

    def run(self, session: Session) -> Session:
        with self.store.lock(session.id):
            session = self.store.load(session.id)  # Load under the lock to avoid stale concurrent resumes.
            try:
                plan = validate_session(self.config, session)
                for turn in plan[len(session.turns):]:
                    self.executor.perform(session, turn)
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
