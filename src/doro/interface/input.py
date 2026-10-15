import json
from pathlib import Path

from doro.domain.models import Config, DoroError, Task
from doro.domain.validation import parse_task


def read_bounded(path: Path, maximum: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum * 4:
        raise DoroError("Input must be a regular bounded file without symlinks")
    text = path.read_text(encoding="utf-8")
    if len(text) > maximum:
        raise DoroError("Input character bound exceeded")
    return text


def load_task(config: Config, path: Path) -> Task:
    return parse_task(json.loads(read_bounded(path, config.limits.max_prompt_chars)))
