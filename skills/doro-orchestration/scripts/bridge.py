#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys


def main() -> None:
    manifest = Path.home() / ".codex" / "skill-docs" / "doro-orchestration.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise SystemExit("도로 협업 실행기의 로컬 등록 파일이 없어. 설치 상태를 확인해줘.")
    value: object = json.loads(manifest.read_text())
    if not isinstance(value, dict) or value.get("version") != 1:
        raise SystemExit("도로 협업 등록 파일 형식이 올바르지 않아.")
    root = value.get("project_root")
    if not isinstance(root, str):
        raise SystemExit("등록된 프로젝트 경로가 없어.")
    executable = Path(root) / "doro"
    if not executable.is_file() or not (Path(root) / "orchestrator.toml").is_file():
        raise SystemExit("등록된 실행기를 찾을 수 없어. 이동한 경로를 다시 등록해줘.")
    os.execv(sys.executable, [sys.executable, str(executable), *sys.argv[1:]])


if __name__ == "__main__":
    main()
