import json

from doro.domain.models import DoroError, Reply
from doro.domain.validation import integer, mapping, number, string
from doro.infrastructure.process import ProcessResult


def parse_codex(output: str) -> Reply:
    messages: list[str] = []
    usage: dict[str, object] | None = None
    session_id = ""
    for line in output.splitlines():
        event = mapping(json.loads(line), "Codex event")
        kind = event.get("type")
        if kind in ("error", "turn.failed"):
            raise DoroError("Codex reported a failed turn: " + json.dumps(event, ensure_ascii=False)[:1000])
        if kind == "thread.started":
            session_id = string(event.get("thread_id"), "thread_id")
        if kind == "item.completed":
            item = mapping(event.get("item"), "item")
            if item.get("type") in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                raise DoroError("Codex attempted a forbidden tool operation")
            if item.get("type") == "agent_message":
                messages.append(string(item.get("text"), "agent_message"))
        if kind == "turn.completed":
            usage = mapping(event.get("usage"), "usage")
    if usage is None or not messages:
        raise DoroError("Codex response lacks a completed turn or message")
    tokens = integer(usage.get("input_tokens"), "input_tokens", low=0, high=10_000_000)
    tokens += integer(usage.get("output_tokens"), "output_tokens", low=0, high=10_000_000)
    return Reply("\n\n".join(messages), tokens, None, session_id)


def parse_claude(output: str) -> Reply:
    events: list[dict[str, object]] = []
    decoder, offset = json.JSONDecoder(), 0
    while offset < len(output):
        if output[offset].isspace():
            offset += 1
            continue
        value, offset = decoder.raw_decode(output, offset)
        events.append(mapping(value, "Claude event"))
    results = [event for event in events if event.get("type") == "result" or "is_error" in event]
    if len(results) != 1:
        raise DoroError("Claude stream needs exactly one final result")
    data = results[0]
    if data.get("is_error") is not False or data.get("subtype") != "success":
        raise DoroError("Claude failed: " + str(data.get("result", data.get("subtype")))[:1000])
    usage = mapping(data.get("usage"), "usage")
    tokens = sum(integer(usage.get(k, 0), k, low=0, high=10_000_000) for k in
                 ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    if data.get("permission_denials"):
        raise DoroError("Claude reported permission denials; stop for inspection")
    return Reply(string(data.get("result"), "result"), tokens,
                 number(data.get("total_cost_usd"), "total_cost_usd"),
                 string(data.get("session_id"), "session_id"), claude_model(events))


def claude_model(events: list[dict[str, object]]) -> str:
    """Retain actual assistant model IDs, including substitutions, never infer from an alias."""
    models: list[str] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        model = mapping(event.get("message"), "Claude assistant message").get("model")
        if model and model not in models:
            models.append(string(model, "model"))
    return ", ".join(models)


def parse_agy(output: str) -> Reply:
    rows = [mapping(json.loads(line), "AGY event") for line in output.splitlines() if line.strip()]
    if len(rows) == 1 and "event" not in rows[0]:
        data, model = rows[0], ""
    else:
        initial = [mapping(row.get("init"), "AGY init") for row in rows if row.get("event") == "init"]
        results = [mapping(row.get("result"), "AGY result") for row in rows if row.get("event") == "result"]
        if len(results) == 1 and results[0].get("status") != "SUCCESS":
            raise DoroError("AGY failed: " + str(results[0].get("error", results[0].get("status")))[:1000])
        if len(initial) != 1 or len(results) != 1:
            raise DoroError("AGY needs one initialization and one final result")
        data, model = results[0], string(initial[0].get("model"), "AGY CLI model")
    if data.get("status") != "SUCCESS":
        raise DoroError("AGY did not complete successfully: " + str(data.get("error", data.get("status")))[:1000])
    usage = mapping(data.get("usage"), "usage")
    return Reply(string(data.get("response"), "response"),
                 integer(usage.get("total_tokens"), "total_tokens", low=0, high=10_000_000),
                 None, string(data.get("conversation_id"), "conversation_id"), model)


def decode_reply(provider: str, result: ProcessResult) -> Reply:
    try:
        if result.returncode:
            detail = (result.stderr or result.stdout)[-1500:]
            raise DoroError(f"{provider} exited {result.returncode}: {detail}")
        return {"codex": parse_codex, "claude": parse_claude, "agy": parse_agy}[provider](result.stdout)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise DoroError(f"{provider} emitted malformed output") from error
