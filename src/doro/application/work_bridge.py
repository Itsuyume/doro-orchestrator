from typing import Callable
from uuid import uuid4

from doro.application.failures import public_error
from doro.application.ports import Runner, Store
from doro.application.turn_executor import TurnExecutor
from doro.domain.checkpoints import decide_checkpoint, request_checkpoint, require_approval, start_summary
from doro.domain.models import Config, DoroError, PlannedTurn, Session, Task
from doro.domain.work import review_count, validate_work, work_text


class WorkBridge:
    """Current GPT Work authors main turns; only Claude is executed externally."""
    def __init__(self, config: Config, store: Store, runner: Runner,
                 notify: Callable[[str], None], check_ready: Callable[[], None] | None = None) -> None:
        self.config = config
        self.store = store
        self.executor = TurnExecutor(config, store, runner, notify)
        self.check_ready = check_ready

    def start(self, task: Task, draft: str, scope: str = "") -> Session:
        session = Session(str(uuid4()), task, self.config.fingerprint, ("work", "claude"),
                          self.config.limits.debate_rounds, mode="work")
        session.turns.append(work_text(self.config, draft, "draft"))
        validate_work(self.config, session)
        session.status = "awaiting_claude"
        request_checkpoint(session, "start", scope or start_summary(self.config, session))
        self.store.save(session)
        self.store.export(session)
        return session

    def review(self, session_id: str) -> Session:
        with self.store.lock(session_id):
            session = self.store.load(session_id)
            validate_work(self.config, session)
            require_approval(session)
            if session.status == "completed" or session.turns[-1].provider != "work":
                raise DoroError("Claude review needs a new Work draft/rebuttal; no duplicate call was made")
            if review_count(session) >= session.rounds:
                raise DoroError("Configured review count reached; Work must make the final judgment")
            try:
                if self.check_ready is not None:
                    self.check_ready()
                phase = "review" if review_count(session) == 0 else "recheck"
                self.executor.perform(session, PlannedTurn("claude", phase))
                session.status = "awaiting_work"
                session.error = ""
                self.store.save(session)
                self.store.export(session)
                return session
            except KeyboardInterrupt:
                session.status, session.error = "interrupted", "User interrupted; no automatic retry"
                self.store.save(session)
                raise
            except (DoroError, OSError, ValueError) as error:
                session.status, session.error = "failed", public_error(error)
                self.store.save(session)
                raise DoroError(session.error) from error

    def write(self, session_id: str, text: str, phase: str) -> Session:
        with self.store.lock(session_id):
            session = self.store.load(session_id)
            validate_work(self.config, session)
            require_approval(session)
            if session.status != "awaiting_work" or session.turns[-1].provider != "claude":
                raise DoroError("A Work reply/final needs a completed Claude review")
            if phase == "rebuttal" and review_count(session) >= session.rounds:
                raise DoroError("Review limit reached; finish with GPT Work's final judgment")
            session.turns.append(work_text(self.config, text, phase))
            session.status = "completed" if phase == "final" else "awaiting_claude"
            session.error = ""
            self.store.save(session)
            self.store.export(session)
            return session

    def reply(self, session_id: str, text: str) -> Session:
        return self.write(session_id, text, "rebuttal")

    def finish(self, session_id: str, text: str) -> Session:
        return self.write(session_id, text, "final")

    def checkpoint(self, session_id: str, kind: str, summary: str) -> Session:
        with self.store.lock(session_id):
            session = self.store.load(session_id)
            validate_work(self.config, session)
            request_checkpoint(session, kind, summary)
            self.store.save(session)
            self.store.export(session)
            return session

    def decide(self, session_id: str, checkpoint_id: str, decision: str) -> Session:
        """Record the human decision from the trusted Work host; never from model output."""
        with self.store.lock(session_id):
            session = self.store.load(session_id)
            validate_work(self.config, session)
            decide_checkpoint(session, checkpoint_id, decision)
            self.store.save(session)
            self.store.export(session)
            return session

    def cancel(self, session_id: str) -> Session:
        with self.store.lock(session_id):
            session = self.store.load(session_id)
            validate_work(self.config, session)
            if session.status in {"running", "completed"}:
                raise DoroError("A running turn must first be interrupted; a completed result cannot be cancelled")
            session.status, session.error = "cancelled", ""
            self.store.save(session)
            self.store.export(session)
            return session
