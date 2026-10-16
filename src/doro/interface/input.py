import json
import hashlib
from pathlib import Path

from doro.domain.models import Config, DoroError, Task
from doro.domain.validation import parse_task


def read_bounded(path: Path, maximum: int, expected_sha256: str | None = None) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum * 4:
        raise DoroError("Input must be a regular bounded file without symlinks")
    raw = path.read_bytes()
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise DoroError("Approved input file changed; no recovery or model call was made")
    text = raw.decode("utf-8")
    if len(text) > maximum:
        raise DoroError("Input character bound exceeded")
    return text


def load_task(config: Config, path: Path, expected_sha256: str | None = None) -> Task:
    return parse_task(json.loads(read_bounded(path, config.limits.max_prompt_chars, expected_sha256)))
