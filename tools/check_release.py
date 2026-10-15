"""Audit the explicit Git staging area before publishing this independent source repo."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_PATHS = {".doro", ".env", ".venv", "__pycache__"}
KEYS = r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[\w]{25,}|AIza[\w-]{25,})"


def main() -> int:
    result = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], cwd=ROOT,
                            check=True, capture_output=True)
    files = [name.decode() for name in result.stdout.split(b"\0") if name]
    if not files:
        print("No staged source files to audit")
        return 1
    failures: list[str] = []
    for name in files:
        path = ROOT / name
        if set(path.relative_to(ROOT).parts) & SENSITIVE_PATHS or path.is_symlink():
            failures.append(f"Disallowed staged path: {name}")
            continue
        content = subprocess.run(["git", "show", ":" + name], cwd=ROOT,
                                 check=True, capture_output=True).stdout
        if len(content) > 300_000:
            failures.append(f"Oversized staged file: {name}")
            continue
        text = content.decode("utf-8")
        if str(Path.home()) in text or re.search(KEYS, text):
            failures.append(f"Personal home path or credential pattern: {name}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Release audit OK: {len(files)} staged public source files; no runtime state or detected credentials")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
