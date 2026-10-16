from dataclasses import dataclass
import json
from pathlib import Path
import tomllib

from doro.domain.models import DoroError
from doro.domain.validation import boolean, integer, keys, mapping, string
from doro.infrastructure.storage import session_key


@dataclass(frozen=True)
class RadarSettings:
    enabled: bool
    connection: Path
    automation: Path
    state_root: Path
    codex: Path
    obsidian: Path
    owner: str
    vault: Path
    remote_seconds: int


def read_mapping(path: Path) -> dict[str, object]:
    if path.is_symlink() or path.stat().st_size > 2_000_000:
        raise DoroError("Radar configuration/state must be a bounded regular file")
    return mapping(json.loads(path.read_text()), str(path))


def load_settings(path: Path) -> RadarSettings:
    data = read_mapping(path)
    keys(data, {"version", "enabled", "connection", "automation", "state_root", "codex", "obsidian",
                "owner", "remote_seconds"}, "radar settings")
    if data["version"] != 1:
        raise DoroError("Unsupported radar configuration")
    paths = {key: Path(string(data[key], key)) for key in
             ("connection", "automation", "state_root", "codex", "obsidian")}
    if any(not p.is_absolute() for p in paths.values()):
        raise DoroError("Radar paths must be absolute")
    if any(p.is_symlink() for key, p in paths.items() if key != "connection"):
        raise DoroError("Radar executable/state paths cannot be symlinks")
    owner = session_key(string(data["owner"], "owner"))
    automation = tomllib.loads(paths["automation"].read_text())
    if automation.get("target_thread_id") != owner or automation.get("id") != "space":
        raise DoroError("Radar owner differs from the existing synchronization route")
    enabled = boolean(data["enabled"], "enabled")
    return RadarSettings(enabled, paths["connection"], paths["automation"], paths["state_root"], paths["codex"],
                         paths["obsidian"], owner, paths["connection"].parents[2],
                         integer(data["remote_seconds"], "remote_seconds", low=300, high=86400))
