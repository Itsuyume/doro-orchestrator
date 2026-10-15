from doro.domain.activity import GATES, PHASES, STATES, activity_title
from doro.domain.models import ChatApproval, ChatContext, ChatMessage, Config, Conversation, DoroError, Exchange, HumanInput, Session, Turn

SENDERS = {"work": "도로 · GPT Work", "codex": "GPT · Codex CLI", "claude": "도로 · Claude Code", "agy": "AGY"}


def turn_message(index: int, turn: Turn, incoming: str = "") -> ChatMessage:
    return ChatMessage(f"turn-{index}", SENDERS[turn.provider], PHASES[turn.phase], turn.text,
                       incoming=incoming, main=turn.provider in {"work", "codex"})


def exchange_message(index: int, exchange: Exchange) -> ChatMessage:
    states = {"running": "응답 생성 중", "failed": "실패한 부분 응답 · 채택하지 않음",
              "interrupted": "중단된 부분 응답 · 채택하지 않음"}
    if exchange.status not in states:
        raise DoroError("Conversation contains an unmatched completed or invalid external attempt")
    text = exchange.output or "아직 받은 응답이 없도로."
    if exchange.error:
        text += "\n\n오류: " + exchange.error
    return ChatMessage(f"attempt-{index}", SENDERS[exchange.provider], PHASES[exchange.phase],
                       text, states[exchange.status], exchange.input, exchange.provider == "codex")


def discussion(session: Session, inputs: tuple[HumanInput, ...] = ()) -> list[ChatMessage]:
    """Merge actual completed turns and external attempts; never invent speaker replies."""
    messages: list[ChatMessage] = []
    cursor = 0
    for index, turn in enumerate(session.turns):
        matched = next((i for i in range(cursor, len(session.exchanges))
                        if matches(session.exchanges[i], turn)), None)
        if matched is None:
            messages.append(turn_message(index, turn))
        else:
            messages.extend(exchange_message(i, session.exchanges[i]) for i in range(cursor, matched))
            messages.append(turn_message(index, turn, session.exchanges[matched].input))
            cursor = matched + 1
        messages.extend(inputs_after(inputs, index + 1))
    messages.extend(exchange_message(i, session.exchanges[i]) for i in range(cursor, len(session.exchanges)))
    return messages


def matches(exchange: Exchange, turn: Turn) -> bool:
    return (exchange.status == "completed" and exchange.provider == turn.provider
            and exchange.phase == turn.phase and exchange.output == turn.text)


def conversation(config: Config, session: Session, label: str = "도로 협업",
                 inputs: tuple[HumanInput, ...] = (), input_enabled: bool = False,
                 contexts: tuple[ChatContext, ...] = ()) -> Conversation:
    request = session.task.message + ("\n\n" + session.task.context if session.task.context else "")
    messages = [ChatMessage("request", "도로 · 작업 범위", "이번 작업 범위", request)]
    messages.extend(discussion(session, inputs))
    if session.error:
        messages.append(ChatMessage("error", "도로 · 실행 상태", "오류", session.error, "중단 · 자동 재시도 없음"))
    usage = (f"Claude 호출 {session.calls.get('claude', 0)}회"
             f" · AGY {'활성' if config.providers['agy'].enabled else '꺼짐'}")
    return Conversation(1, session.id, activity_title(config, session, label), STATES[session.status],
                        usage, tuple(messages), reply_hint(session.status, label), input_enabled,
                        session.checkpoints[-1].id if session.status == "awaiting_approval" else "", label, contexts,
                        config.providers['claude'].enabled, config.providers['agy'].enabled, current_approval(session, inputs))


def current_approval(session: Session, inputs: tuple[HumanInput, ...]) -> ChatApproval | None:
    if session.status != "awaiting_approval":
        return None
    gate = session.checkpoints[-1]
    decision = next((note.decision for note in inputs if note.checkpoint_id == gate.id and note.decision), "")
    return ChatApproval(gate.id, GATES[gate.kind], gate.brief, gate.summary, bool(decision), decision)


def context_summary(session: Session, label: str, inputs: tuple[HumanInput, ...]) -> ChatContext:
    events = len(session.turns) + sum(exchange.status != "completed" for exchange in session.exchanges)
    events += sum(1 + bool(note.response) for note in inputs)
    approval = current_approval(session, inputs)
    return ChatContext(session.id, label, STATES[session.status], approval is not None and not approval.response_pending,
                       events, sum(note.state == "queued" for note in inputs), session.status in {"completed", "cancelled"})


def reply_hint(status: str, label: str) -> str:
    if status == "awaiting_approval":
        return "이 창의 승인·보류 버튼으로 답해줘도로."
    if status in {"completed", "cancelled"}:
        return "여기서 이 작업의 새 협업을 요청할 수 있도로."
    return "질문이나 방향 변경은 아래 입력창에 보내줘도로."


def input_messages(note: HumanInput) -> tuple[ChatMessage, ...]:
    message = ChatMessage(note.id, "나", "승인 답변" if note.decision else "개입 메시지", note.text,
                          "도로 확인" if note.state == "read" else "Work 수신 대기", from_user=True)
    if note.response:
        return message, ChatMessage(note.id + "-reply", "도로 · GPT Work", "내 메시지에 대한 답", note.response, main=True)
    return (message,)


def inputs_after(inputs: tuple[HumanInput, ...], after_turn: int) -> tuple[ChatMessage, ...]:
    return tuple(message for note in inputs if note.after_turn == after_turn for message in input_messages(note))


def conversation_text(view: Conversation) -> str:
    lines = [view.title, view.usage]
    for message in view.messages:
        lines += ["", f"{message.sender} · {message.phase} · {message.state}", message.text]
    if view.approval:
        lines += ["", view.approval.kind, view.approval.brief, view.approval.details]
    return "\n".join([*lines, "", view.reply_hint]) + "\n"
