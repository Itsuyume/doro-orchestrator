import time
from typing import Callable

from doro.application.exchange_observer import ExchangeObserver
from doro.application.failures import public_error
from doro.application.ports import Runner, Store
from doro.application.prompts import build_prompt
from doro.domain.models import Config, DoroError, Exchange, PlannedTurn, Session, Turn
from doro.domain.policy import allow_call, ensure_public, quota_retry


class TurnExecutor:
    """Execute one external model turn. The caller owns session locking and the turn plan."""
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
        exchange = Exchange(turn.provider, turn.phase, prompt)
        session.exchanges.append(exchange)
        self.store.save(session)
        self.notify(f"{session.id}: {turn.provider} / {turn.phase}")
        timeout = (self.config.limits.timeout_seconds if quota_retry(session, turn.provider)
                   else min(self.config.limits.timeout_seconds, self.config.limits.session_seconds - session.seconds_used))
        started = time.monotonic()
        observer = ExchangeObserver(self.config, self.store, session, exchange)
        try:
            reply = self.runner.call(turn.provider, prompt, self.store.workspace(session.id), timeout, observer.receive)
            session.tokens_used += reply.tokens
            if reply.cost_usd is not None:
                session.reported_usd += reply.cost_usd
            if session.tokens_used > self.config.limits.max_tokens and not quota_retry(session, turn.provider):
                raise DoroError("Reported token limit exceeded; stop before forwarding")
            if session.reported_usd > self.config.limits.session_reported_usd and not quota_retry(session, turn.provider):
                raise DoroError("Reported cost limit exceeded; stop before forwarding")
            if len(reply.text) > self.config.limits.max_response_chars:
                raise DoroError("Response limit exceeded; nothing was truncated or forwarded")
            ensure_public(reply.text)
            session.turns.append(Turn(turn.provider, turn.phase, reply.text, reply.tokens,
                                      reply.cost_usd, reply.native_session_id, reply.model))
            exchange.output, exchange.status = reply.text, "completed"
        except KeyboardInterrupt:
            exchange.status, exchange.error = "interrupted", "User interrupted; partial response is not a final result"
            raise
        except (DoroError, OSError, ValueError) as error:
            exchange.status, exchange.error = "failed", public_error(error)
            raise
        finally:
            session.seconds_used += time.monotonic() - started
            self.store.save(session)
