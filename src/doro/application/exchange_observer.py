import time

from doro.application.ports import Store
from doro.domain.models import Config, DoroError, Exchange, Session
from doro.domain.policy import ensure_public


class ExchangeObserver:
    """Persist only public response text; partial output is never conversation input."""
    def __init__(self, config: Config, store: Store, session: Session, exchange: Exchange) -> None:
        self.maximum = config.limits.max_response_chars
        self.store, self.session, self.exchange = store, session, exchange
        self.last_save = 0.0

    def receive(self, text: str) -> None:
        combined = self.exchange.output + text
        if len(combined) > self.maximum:
            raise DoroError("Streaming response limit exceeded; process terminated")
        ensure_public(combined)
        self.exchange.output = combined
        now = time.monotonic()
        if now - self.last_save >= 0.25:
            self.store.save(self.session)
            self.last_save = now
