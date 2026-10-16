"""One user-wide viewer lease, with serialized requests and an explicit project owner."""
from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from doro.domain.models import DoroError
from doro.domain.validation import mapping
from doro.infrastructure.storage import private_directory


def runtime_directory() -> Path:
    return Path.home() / "Library/Application Support/도로협업"


def acquire(descriptor: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


@contextmanager
def viewer_locks(directory: Path, timeout: float = 15) -> Iterator[int | None]:
    private_directory(directory)
    request = os.open(directory / "request.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not acquire(request, timeout):
            raise DoroError("협업창을 여는 중이도로. 잠시 뒤 다시 열어줘도로. 두 번째 창은 만들지 않았도로.")
        with instance_descriptor(directory) as descriptor:
            yield descriptor
    finally:
        os.close(request)


@contextmanager
def instance_descriptor(directory: Path) -> Iterator[int | None]:
    descriptor = os.open(directory / "viewer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        yield descriptor if acquire(descriptor, 0) else None
    finally:
        os.close(descriptor)


def instance_owner(directory: Path, root: Path, config: Path, *, claim: bool) -> None:
    path = directory / "owner.json"
    if path.is_symlink():
        raise DoroError("Viewer owner symlinks are not allowed")
    expected = {"version": 1, "project": str(root.resolve()), "config": str(config.resolve())}
    if not claim:
        if not path.is_file() or path.stat().st_size > 16000:
            raise DoroError("실행 중인 협업창의 연결을 확인하지 못했도로. 두 번째 창은 만들지 않았도로.")
        if mapping(json.loads(path.read_text()), "viewer owner") != expected:
            raise DoroError("다른 설치본의 협업창이 이미 실행 중이도로. 그 창을 종료한 뒤 다시 열어줘도로.")
        return
    temporary = directory / (str(uuid4()) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(expected, output)
    os.replace(temporary, path)
