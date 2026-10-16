"""An optional window lifetime gate; visibility changes do not end the viewer lease."""
from collections.abc import Callable
import json
import os
from pathlib import Path
from uuid import uuid4

from doro.domain.models import DoroError
from doro.domain.validation import boolean, keys, mapping
from doro.infrastructure.storage import private_directory
from doro.infrastructure.viewer_instance import instance_descriptor, runtime_directory


def required(state: Path) -> bool:
    path = state / "window-policy.json"
    if path.is_symlink():
        raise DoroError("Window collaboration policy cannot be a symlink")
    if not path.exists():
        return False
    if path.stat().st_size > 1024:
        raise DoroError("Window collaboration policy is too large")
    data = mapping(json.loads(path.read_text()), "window collaboration policy")
    keys(data, {"version", "requires_running_window"}, "window collaboration policy")
    if data["version"] != 1:
        raise DoroError("Unsupported window collaboration policy")
    return boolean(data["requires_running_window"], "requires_running_window")


def enable(state: Path) -> None:
    required(state)  # Validate the existing file before replacing it.
    private_directory(state)
    temporary = state / (str(uuid4()) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump({"version": 1, "requires_running_window": True}, output)
    os.replace(temporary, state / "window-policy.json")


def viewer_identity(project: Path, runtime: Path) -> tuple[int, int] | None:
    if not runtime.is_dir():
        return None
    with instance_descriptor(runtime) as descriptor:
        if descriptor is not None:
            return None
        owner = runtime / "owner.json"
        if owner.is_symlink() or not owner.is_file() or owner.stat().st_size > 16000:
            raise DoroError("협업창 소유 연결을 확인하지 못했도로. 외부 호출은 차단했도로.")
        data = mapping(json.loads(owner.read_text()), "viewer owner")
        keys(data, {"version", "project", "config"}, "viewer owner")
        if data["version"] != 1 or data["project"] != str(project.resolve()):
            raise DoroError("다른 설치본의 협업창이도로. 이 프로젝트의 외부 호출은 차단했도로.")
        info = owner.stat()
        return info.st_dev, info.st_ino


class WindowLease:
    def __init__(self, project: Path, runtime: Path) -> None:
        self.project, self.runtime = project.resolve(), runtime
        self.identity = viewer_identity(project, runtime)
        if self.identity is None:
            raise DoroError("도로협업이 꺼져 있어 외부 협업을 시작하지 않았도로. 도로협업을 먼저 열어줘도로.")

    def active(self) -> bool:
        return viewer_identity(self.project, self.runtime) == self.identity


def collaboration_guard(state: Path) -> Callable[[], bool] | None:
    if not required(state):
        return None
    return WindowLease(state.parent, runtime_directory()).active
