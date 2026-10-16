"""Prepare or install one official input-notification hook; never grants hook trust."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile


def prepare(path: Path, bridge: Path) -> tuple[bytes, bytes, dict[str, object]]:
    if path.is_symlink() or not bridge.is_file() or bridge.is_symlink():
        raise ValueError("Use a regular hook file and the installed Doro bridge")
    before = path.read_bytes() if path.exists() else b""
    data = json.loads(before) if path.exists() else {"hooks": {}}
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        raise ValueError("The existing hooks configuration needs review; nothing was changed")
    entries = data["hooks"].get("PostToolUse", [])
    if not isinstance(entries, list):
        raise ValueError("Existing PostToolUse hooks must be a list")
    handler = {"matcher": ".*", "hooks": [{"type": "command",
               "command": shlex.join([sys.executable, str(bridge), "inputs", "notify-hook"]),
               "async": True, "timeout": 2, "additionalContextLimit": 1200}]}
    if handler in entries:
        return before, before, handler
    if any("notify-hook" in str(entry) for entry in entries):
        raise ValueError("An existing Doro input hook differs; compare it before replacing")
    data["hooks"]["PostToolUse"] = [*entries, handler]
    after = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    return before, after, handler


def install(codex: Path, bridge: Path, *, apply: bool = False) -> dict[str, object]:
    path = codex / "hooks.json"
    if codex.is_symlink() or not codex.is_dir():
        raise ValueError("Use the existing regular Codex settings directory")
    before, after, handler = prepare(path, bridge)
    result: dict[str, object] = {"path": str(path), "handler": handler,
                                "hook_trust": "requires normal /hooks review", "installed": False}
    if not apply or before == after:
        result["installed"] = before == after
        return result
    archive = codex / "skill-archives" / datetime.now().strftime("%Y-%m-%d/doro-input-%H%M%S-%f")
    archive.mkdir(parents=True, mode=0o700)
    if before:
        backup = archive / "hooks.json"
        backup.write_bytes(before)
        backup.chmod(0o600)
        result["backup"] = str(backup)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=codex, prefix=".doro-input-", delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(after)
            handle.flush()
            os.fsync(handle.fileno())
        current = path.read_bytes() if path.exists() else b""
        if current != before or path.is_symlink():
            raise ValueError("Hook settings changed during preparation; nothing was replaced")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    result["installed"] = True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--bridge", type=Path, default=Path.home() / ".codex/skills/doro-orchestration/scripts/bridge.py")
    parser.add_argument("--apply", action="store_true", help="Save the reviewed configuration; does not trust it")
    args = parser.parse_args()
    print(json.dumps(install(args.codex_home, args.bridge, apply=args.apply), ensure_ascii=False, indent=2))
