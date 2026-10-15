"""Install one verified local workflow without overwriting another skill or account config."""
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "doro-orchestration"


def install(user_directory: Path, project: Path = ROOT) -> tuple[Path, Path]:
    source = project / "skills" / SKILL_NAME
    destination = user_directory / ".codex" / "skills" / SKILL_NAME
    alternate = user_directory / ".agents" / "skills" / SKILL_NAME
    if alternate.exists():
        raise SystemExit("Another installation exists in .agents/skills; refusing a duplicate")
    if destination.is_symlink():
        raise SystemExit("Existing skill is a symlink; inspect its ownership before updating")
    if destination.exists():
        for path in source.rglob("*"):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_file() and (not (destination / path.relative_to(source)).is_file()
                                   or path.read_bytes() != (destination / path.relative_to(source)).read_bytes()):
                raise SystemExit("Existing skill differs; inspect local edits before updating")
    else:
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    docs = user_directory / ".codex" / "skill-docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / (SKILL_NAME + ".json")
    if path.is_symlink():
        raise SystemExit("Registration file cannot be a symlink")
    path.write_text(json.dumps({"version": 1, "project_root": str(project), "skill_root": str(destination),
                               "trigger": "explicit user request during project work",
                               "main": "current GPT Work chat", "external": ["claude"],
                               "agy_enabled": False, "python_executable": sys.executable,
                               "launch_path": os.environ.get("PATH", os.defpath)}, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)
    return destination, path


if __name__ == "__main__":
    installed, registered = install(Path.home())
    print("Installed:", installed)
    print("Registered:", registered)
