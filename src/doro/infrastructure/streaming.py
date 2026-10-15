from collections.abc import Callable
import json

from doro.domain.models import DoroError
from doro.domain.validation import mapping, string


class ClaudeTextStream:
    """Newline-delimited transport parser. Excludes internal thinking and raw metadata."""
    def __init__(self, receive: Callable[[str], None]) -> None:
        self.receive = receive
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> None:
        self.buffer.extend(chunk)
        while b"\n" in self.buffer:
            raw, _, remaining = self.buffer.partition(b"\n")
            self.buffer = remaining
            self.event(bytes(raw))

    def event(self, raw: bytes) -> None:
        try:
            data = mapping(json.loads(raw), "Claude stream event")
        except (json.JSONDecodeError, UnicodeError) as error:
            raise DoroError("Claude emitted malformed streaming output") from error
        if data.get("type") != "stream_event":
            return
        event = mapping(data.get("event"), "Claude inner event")
        if event.get("type") == "content_block_start":
            block = mapping(event.get("content_block"), "Claude content block")
            if block.get("type") == "tool_use":
                raise DoroError("Claude attempted a forbidden tool operation")
        if event.get("type") != "content_block_delta":
            return
        delta = mapping(event.get("delta"), "Claude delta")
        if delta.get("type") == "text_delta":
            text = string(delta.get("text"), "Claude text delta", empty=True)
            self.receive(text)

    def finish(self) -> None:
        if self.buffer:
            self.event(bytes(self.buffer))
            self.buffer.clear()
