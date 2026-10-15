from dataclasses import dataclass, field


class DoroError(Exception):
    """A visible failure at a policy, persistence, or external process boundary."""


@dataclass(frozen=True)
class Task:
    message: str
    classification: str
    allowed_providers: tuple[str, ...]
    context: str

    def to_dict(self) -> dict[str, object]:
        return {"message": self.message, "classification": self.classification,
                "allowed_providers": list(self.allowed_providers), "context": self.context}


@dataclass(frozen=True)
class Provider:
    enabled: bool
    command: tuple[str, ...]
    model: str
    effort: str
    max_calls: int


@dataclass(frozen=True)
class Limits:
    debate_rounds: int
    max_calls: int
    daily_calls: int
    timeout_seconds: int
    session_seconds: int
    max_prompt_chars: int
    max_response_chars: int
    max_process_bytes: int
    max_tokens: int
    claude_call_usd: float
    session_reported_usd: float


@dataclass(frozen=True)
class Config:
    providers: dict[str, Provider]
    limits: Limits
    fingerprint: str
    roles: dict[str, str]

    def participants(self) -> tuple[str, ...]:
        return tuple(name for name, provider in self.providers.items() if provider.enabled)


@dataclass(frozen=True)
class PlannedTurn:
    provider: str
    phase: str


@dataclass(frozen=True)
class Reply:
    text: str
    tokens: int
    cost_usd: float | None
    native_session_id: str


@dataclass(frozen=True)
class Turn:
    provider: str
    phase: str
    text: str
    tokens: int
    cost_usd: float | None
    native_session_id: str


@dataclass
class Session:
    id: str
    task: Task
    config_fingerprint: str
    participants: tuple[str, ...]
    rounds: int
    turns: list[Turn] = field(default_factory=list)
    calls: dict[str, int] = field(default_factory=dict)
    tokens_used: int = 0
    reported_usd: float = 0.0
    claude_reserved_usd: float = 0.0
    seconds_used: float = 0.0
    status: str = "ready"
    error: str = ""
    mode: str = "cli"
