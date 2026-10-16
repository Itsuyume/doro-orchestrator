from dataclasses import dataclass, field
HUMAN_INPUT_LIMIT = 2000

class DoroError(Exception):
    """A visible failure at a policy, persistence, or external process boundary."""

@dataclass(frozen=True)
class OwnerRoute:
    session_id: str
    thread_id: str
    label: str


@dataclass(frozen=True)
class PetSwap:
    original_pet_id: str
    sessions: tuple[str, ...]
    stage: str


@dataclass(frozen=True)
class ApprovalReceipt:
    id: str
    session_id: str
    checkpoint_id: str
    owner_thread_id: str
    decision: str
    answer: str
    delivered: bool = False


@dataclass(frozen=True)
class ChatMessage:
    id: str
    sender: str
    phase: str
    text: str
    state: str = "completed"
    incoming: str = ""
    main: bool = False
    from_user: bool = False
    retryable: bool = False


@dataclass(frozen=True)
class HumanInput:
    id: str
    session_id: str
    owner_thread_id: str
    text: str
    after_turn: int
    checkpoint_id: str
    state: str = "queued"
    decision: str = ""
    response: str = ""


@dataclass(frozen=True)
class ChatContext:
    session_id: str
    label: str
    status: str
    needs_input: bool
    event_count: int
    queued_inputs: int
    finished: bool = False


@dataclass(frozen=True)
class ChatApproval:
    checkpoint_id: str
    kind: str
    brief: str
    details: str
    response_pending: bool = False
    response_decision: str = ""


@dataclass(frozen=True)
class ModelSelection:
    model: str
    effort: str
    actual_model: str
    models: tuple[tuple[str, str], ...]
    efforts: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Conversation:
    version: int
    session_id: str
    title: str
    status: str
    usage: str
    messages: tuple[ChatMessage, ...]
    reply_hint: str
    input_enabled: bool = False
    checkpoint_id: str = ""
    label: str = "도로 협업"
    contexts: tuple[ChatContext, ...] = ()
    claude_enabled: bool = False
    agy_enabled: bool = False
    approval: ChatApproval | None = None
    model_selection: ModelSelection | None = None
    input_limit: int = HUMAN_INPUT_LIMIT


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
    model: str = ""


@dataclass(frozen=True)
class Turn:
    provider: str
    phase: str
    text: str
    tokens: int
    cost_usd: float | None
    native_session_id: str
    model: str = ""


@dataclass
class Checkpoint:
    id: str
    kind: str
    summary: str
    resume_status: str
    decision: str = "pending"
    brief: str = ""


@dataclass
class Exchange:
    provider: str
    phase: str
    input: str
    output: str = ""
    status: str = "running"
    error: str = ""


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
    checkpoints: list[Checkpoint] = field(default_factory=list)
    exchanges: list[Exchange] = field(default_factory=list)
    retry_until_quota: bool = False
    retry_instructions: str = ""
