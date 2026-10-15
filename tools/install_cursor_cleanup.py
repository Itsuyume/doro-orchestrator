"""Install reviewed user-level cleanup hooks; never grants hook trust."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
MARKER = "<!-- cursor-cleanup:start -->"


def write_private(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".cursor-cleanup-", delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def definitions(directory: Path) -> dict[str, list[dict[str, object]]]:
    command = f'/usr/bin/python3 "{directory / "lifecycle.py"}"'
    common = {"type": "command", "command": command, "timeout": 5}
    ending = {**common, "timeout": 3}
    return {
        "PreToolUse": [{"matcher": "cua_repl.*(js|js_reset)$", "hooks": [common]}],
        "PostToolUse": [{"matcher": "cua_repl.*js_reset$", "hooks": [ending]}],
        "Stop": [{"hooks": [common]}],
        "Interrupt": [{"hooks": [ending]}],
        "SessionEnd": [{"hooks": [ending]}],
    }


def instruction(directory: Path) -> str:
    command = f'/usr/bin/python3 "{directory / "lifecycle.py"}"'
    return f'''{MARKER}
## 화면 조작 후 포인터 정리

- 화면 조작을 시작하기 전에 `{command} begin`으로 현재 작업의 화면 사용을 등록한다. 웹·앱의 실제 조작은 계속 승인된 CUA 도구만 사용한다.
- 마지막 화면 검증이 끝나면 CUA 세션을 reset한 뒤 `{command} finish`와 `{command} status`를 실행한다. 포인터 창이 0개인지 확인하고 실패나 다른 작업 때문에 정리를 미뤘으면 완료라고 하지 않는다.
- 이 정리는 화면 조작 보조 앱이 소유한 Software Cursor 창에 한정한다. 다른 화면 작업의 사용권이 남아 있으면 보조 앱을 종료하지 않는다. ChatGPT 본체·도로 펫·작업창·계정 설정·보안 권한·브라우저 세션은 정리 대상으로 삼지 않는다.
- 종료·중단 훅은 한 번의 정상 신뢰 검토 후에만 동작한다. 신뢰 해시를 직접 쓰거나 검토를 우회하지 않는다. 상태 파일·로그에는 작업 식별자와 창 개수만 저장하며 입력·화면·대화 본문은 저장하지 않는다.
<!-- cursor-cleanup:end -->
'''


def install(user: Path, sdk: Path | None) -> dict[str, str]:
    directory = user / ".codex/hooks/cursor_cleanup"
    if directory.exists():
        raise ValueError("Cursor cleanup already exists; compare local edits before updating")
    hooks_path, agents_path = user / ".codex/hooks.json", user / ".codex/AGENTS.md"
    if hooks_path.is_symlink() or agents_path.is_symlink() or directory.parent.is_symlink():
        raise ValueError("Hook installation paths cannot be symlinks")
    hooks = json.loads(hooks_path.read_text()) if hooks_path.exists() else {"hooks": {}}
    agents = agents_path.read_text() if agents_path.exists() else ""
    if MARKER in agents:
        raise ValueError("An existing cleanup instruction must be reviewed before changing")
    original = {path: path.read_bytes() for path in (hooks_path, agents_path) if path.exists()}
    with tempfile.TemporaryDirectory() as tmp:
        binary = Path(tmp) / "inspect-cursors"
        flags = ["-sdk", str(sdk)] if sdk else []
        subprocess.run(["xcrun", "swiftc", *flags, "-swift-version", "6", "-warnings-as-errors",
                        str(ROOT / "cursor_cleanup/inspector.swift"), "-o", str(binary)], check=True, timeout=60)
        archive = user / ".codex/skill-archives" / datetime.now().strftime("%Y-%m-%d/cursor-cleanup-%H%M%S")
        archive.mkdir(parents=True, mode=0o700)
        for path, data in original.items():
            assert path.read_bytes() == data, f"Configuration changed during preparation: {path.name}"
            (archive / path.name).write_bytes(data)
            (archive / path.name).chmod(0o600)
        directory.mkdir(parents=True, mode=0o700)
        for source in (ROOT / "cursor_cleanup").glob("*"):
            if source.is_file():
                shutil.copy2(source, directory / source.name)
        shutil.copy2(binary, directory / binary.name)
    (directory / "inspect-cursors").chmod(0o700)
    for name, entries in definitions(directory).items():
        hooks.setdefault("hooks", {}).setdefault(name, []).extend(entries)
    write_private(hooks_path, (json.dumps(hooks, ensure_ascii=False, indent=2) + "\n").encode())
    write_private(agents_path, (agents.rstrip() + "\n\n" + instruction(directory)).encode())
    manifest = {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in directory.iterdir() if path.is_file()}
    record = user / ".codex/skill-docs/cursor-cleanup.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"installed": str(directory), "backup": str(archive), "files": manifest,
                                  "hook_trust": "requires user review", "source": str(ROOT)}, indent=2) + "\n")
    record.chmod(0o600)
    return {"installed": str(directory), "backup": str(archive), "hook_trust": "requires user review"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path)
    args = parser.parse_args()
    print(json.dumps(install(Path.home(), args.sdk), ensure_ascii=False))
