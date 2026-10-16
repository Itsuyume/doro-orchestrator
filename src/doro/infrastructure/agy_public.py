"""AGY public-text boundary: verified client, fresh workspace and no inherited customizations."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time

from doro.domain.models import DoroError
from doro.domain.policy import ensure_public
from doro.domain.validation import mapping
from doro.infrastructure.process import ProcessResult, execute

AGENT = "doro-public-review"
PROFILE = """---
name: doro-public-review
description: Review only the explicitly supplied public text.
tools: [finish]
mainAgent: true
subagent: false
commandExecutionPolicy: off
mcpServers: []
skills: []
plugins: []
---
Only discuss the explicit public packet. Never use files, commands, browser, MCP,
subagents, other projects or previous conversations. Do not show internal reasoning.
GPT Work owns implementation and final judgment. Return concise Korean feedback.
"""


def check_customizations(home: Path) -> None:
    paths = (".gemini/GEMINI.md", ".gemini/config/hooks.json", ".gemini/config/rules",
             ".gemini/config/skills", ".gemini/config/agents", ".gemini/antigravity-cli/hooks.json",
             ".gemini/antigravity/GEMINI.md", ".agents/AGENTS.md")
    if any((home / name).exists() or (home / name).is_symlink() for name in paths):
        raise DoroError("AGY 전역 지침·훅·스킬이 있도로. 공개 입력 경계를 검토하기 전에는 호출하지 않도로.")
    for name in (".gemini/settings.json", ".gemini/antigravity-cli/settings.json"):
        settings = home / name
        if settings.is_symlink() or (settings.exists() and json.loads(settings.read_text()) != {}):
            raise DoroError("AGY 전역 설정을 확인해야 하도로. 계정이나 권한을 자동 변경하지 않았도로.")


def verified_binary(root: Path, *, hash_file: bool = False) -> Path:
    binary = root / "bin/agy"
    receipt = root / "agy/verification.json"
    if (binary.is_symlink() or not binary.is_file() or receipt.is_symlink()
            or not receipt.is_file() or receipt.stat().st_size > 16000):
        raise DoroError("AGY 연결 점검이 필요하도로.")
    data = mapping(json.loads(receipt.read_text()), "AGY verification")
    info = binary.stat()
    if (data.get("version") != 1 or data.get("boundary_verified") is not True
            or info.st_size != data.get("binary_size") or info.st_mtime_ns != data.get("binary_mtime_ns")):
        raise DoroError("AGY 실행 파일이 점검 기록과 다르도로. 다시 확인해줘도로.")
    if hash_file:
        with binary.open("rb") as incoming:
            if hashlib.file_digest(incoming, "sha512").hexdigest() != data.get("binary_sha512"):
                raise DoroError("AGY 실행 파일 해시가 바뀌었도로. 호출하지 않았도로.")
    return binary


def availability(root: Path) -> tuple[bool, str]:
    try:
        verified_binary(root)
        check_customizations(Path.home())
    except (DoroError, OSError, ValueError) as error:
        return False, str(error)
    return True, "공개 입력만 검토하도로."


class AgyStreamGuard:
    def __init__(self, model: str) -> None:
        self.model = model
        self.pending = b""
        self.initialized = False
        self.finished = False

    def feed(self, chunk: bytes) -> None:
        self.pending += chunk
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            if line.strip():
                self.read(line)

    def read(self, line: bytes) -> None:
        event = mapping(json.loads(line), "AGY event")
        kind = event.get("event")
        if self.finished or kind not in ("init", "result", "step_update"):
            raise DoroError("AGY 응답 순서나 이벤트 형식을 확인하지 못했도로.")
        if kind == "result":
            status = mapping(event.get("result"), "AGY result").get("status")
            if not self.initialized and status == "SUCCESS":
                raise DoroError("AGY 초기화 확인 전에 성공 응답을 받았도로.")
            self.finished = True
            return
        if kind == "init":
            data = mapping(event.get("init"), "AGY init")
            if self.initialized or data.get("model") != self.model or data.get("permission_mode") != "request-review":
                raise DoroError("AGY 모델·권한 초기화가 지정과 다르도로.")
            self.initialized = True
            return
        if not self.initialized:
            raise DoroError("AGY 초기화 확인 전에 응답을 받았도로.")
        self.read_step(mapping(event.get("step_update"), "AGY step"))

    def read_step(self, step: dict[str, object]) -> None:
        kind = step.get("step_type")
        if kind not in ("user_input", "agent_response", "tool", "checkpoint"):
            name = kind if isinstance(kind, str) and re.fullmatch("[a-z_]{1,40}", kind) else "unknown"
            raise DoroError(f"AGY 단계 형식을 확인해야 하도로: {name}. 응답을 채택하지 않았도로.")
        if step.get("subagent_info"):
            raise DoroError("AGY 하위 에이전트 요청을 중단했도로.")
        if kind == "tool":
            info = mapping(step.get("tool_info", {}), "AGY tool")
            if step.get("tool_name") == "finish" and info.get("name", "finish") == "finish":
                return
            raise DoroError("AGY가 텍스트 검토 밖의 도구를 요청했도로. 중단하고 응답을 채택하지 않았도로.")
        if step.get("tool_info") or step.get("tool_name"):
            raise DoroError("AGY 도구 요청의 단계가 맞지 않아 중단했도로.")

    def finish(self) -> None:
        if self.pending.strip():
            self.read(self.pending)
        self.pending = b""
        if not self.finished:
            raise DoroError("AGY 최종 응답을 확인하지 못했도로.")


def run_public(argv: list[str], prompt: str, model: str, root: Path, timeout: float, bound: int) -> ProcessResult:
    ensure_public(prompt)
    binary = verified_binary(root, hash_file=True)
    check_customizations(Path.home())
    if Path(argv[0]) != binary:
        raise DoroError("AGY must use the verified local client")
    with tempfile.TemporaryDirectory(prefix="doro-agy-public-") as tmp:
        cwd = Path(tmp)
        started = time.monotonic()
        plugins = execute([str(binary), "plugins", "list", "--json"], "", cwd, min(timeout, 15), 100000)
        if plugins.returncode or json.loads(plugins.stdout) != []:
            raise DoroError("AGY 플러그인이 있거나 확인하지 못했도로. 검토 후 다시 연결해줘도로.")
        agent = cwd / ".agents/agents"
        agent.mkdir(parents=True, mode=0o700)
        path = agent / (AGENT + ".md")
        path.write_text(PROFILE)
        path.chmod(0o600)
        stream = AgyStreamGuard(model)
        data = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise DoroError("AGY preflight exceeded its deadline; no model prompt was sent")
        verified_binary(root, hash_file=True)
        check_customizations(Path.home())
        result = execute(argv, data, cwd, remaining, bound, stream.feed)
        if result.returncode == 0:
            stream.finish()
        return result
