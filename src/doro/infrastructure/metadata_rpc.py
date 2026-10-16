"""Read Page versions through the official app-server, without generating a turn."""
from collections.abc import Sequence
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from doro.domain.models import DoroError
from doro.domain.validation import integer, mapping, string
from doro.infrastructure.process import terminate


class MetadataClient:
    def __init__(self, binary: Path, cwd: Path, timeout: float = 45) -> None:
        self.process = subprocess.Popen([str(binary), "app-server", "--stdio"], cwd=cwd,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, start_new_session=True)
        if self.process.stdout is None or self.process.stdin is None:
            raise DoroError("Metadata client pipes were not created")
        self.reader, self.writer = self.process.stdout, self.process.stdin
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.reader, selectors.EVENT_READ)
        self.timeout, self.buffer, self.counter = timeout, b"", 0

    def close(self) -> None:
        terminate(self.process)
        self.selector.close()
        self.reader.close()
        self.writer.close()

    def line(self, deadline: float) -> bytes:
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise DoroError("Page metadata connection timed out; Work was not started")
            chunk = os.read(self.reader.fileno(), 65536)
            if not chunk:
                raise DoroError("Page metadata connection closed; Work was not started")
            self.buffer += chunk
            if len(self.buffer) > 2_000_000:
                raise DoroError("Page metadata response exceeded the transport limit")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line

    def request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        if method not in {"initialize", "thread/start", "mcpServer/tool/call"}:
            raise DoroError("Radar RPC does not permit model generation or other methods")
        self.counter += 1
        request_id = self.counter
        self.writer.write(json.dumps({"id": request_id, "method": method, "params": params}).encode() + b"\n")
        self.writer.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            response = mapping(json.loads(self.line(deadline)), "metadata RPC")
            if "method" in response and "id" in response:
                raise DoroError("Metadata access requires user interaction; no automatic approval")
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = mapping(response["error"], "metadata RPC error")
                raise DoroError("Metadata RPC failed: " + string(error["message"], "error message"))
            return mapping(response.get("result"), "metadata RPC result")

    def start(self) -> str:
        self.request("initialize", {"clientInfo": {"name": "doro_shared_radar", "version": "1.0.0"},
                                    "capabilities": {"experimentalApi": True, "explicitGatewayOauth": True}})
        self.writer.write(b'{"method":"initialized","params":{}}\n')
        self.writer.flush()
        result = self.request("thread/start", {"ephemeral": True})
        return string(mapping(result.get("thread"), "ephemeral context").get("id"), "context id")

    def version(self, context: str, page_id: str) -> int:
        result = self.request("mcpServer/tool/call", {
            "threadId": context, "server": "codex_apps", "tool": "chatgpt_space.read_page",
            "arguments": {"page_id": page_id, "include_content": False}})
        if result.get("isError"):
            raise DoroError("Space metadata read failed; no model-based fallback")
        data = mapping(result.get("structuredContent"), "Page metadata result")
        metadata = mapping(data.get("metadata"), "Page metadata")
        if metadata.get("page_id") != page_id or data.get("content") is not None:
            raise DoroError("Space returned a different Page or an unexpected body")
        return integer(metadata.get("current_sequence"), "Page sequence", low=0, high=2**63 - 1)


def page_versions(binary: Path, cwd: Path, pages: Sequence[str]) -> dict[str, int]:
    client = MetadataClient(binary, cwd)
    try:
        context = client.start()
        return {page: client.version(context, page) for page in pages}
    finally:
        client.close()
