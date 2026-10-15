import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from doro.domain.models import DoroError
from doro.infrastructure.process import SAFE_ENV
from doro.infrastructure.storage import private_directory, session_key
from doro.infrastructure.storage import LocalStore
from doro.infrastructure.pet_swap import PetSwapLedger
from doro.infrastructure.viewer_state import viewer_lock, wait_for_ack, write_request


def native_sdk(root: Path) -> list[str]:
    path = root / ".doro/native/sdk-path"
    if not path.exists():
        return []
    if path.is_symlink() or path.stat().st_size > 4096:
        raise DoroError("Invalid local native SDK configuration")
    sdk = path.read_text().strip()
    if not sdk or not Path(sdk).is_dir():
        raise DoroError("The explicitly configured native SDK is unavailable")
    return ["-sdk", sdk]


def viewer_app(root: Path) -> Path:
    if sys.platform != "darwin" or shutil.which("xcrun") is None:
        raise DoroError("Native chat needs macOS and Swift command-line tools. Use chat --text for local text.")
    sources = sorted((root / "native/DoroChat").glob("*.swift"))
    if not sources:
        raise DoroError("Native chat source files are missing")
    sdk = native_sdk(root)
    digest = hashlib.sha256(b"swift6-integrated-pet-v2" + str(sdk).encode() + b"".join(path.read_bytes() for path in sources)).hexdigest()[:20]
    private_directory(root / ".doro/native")
    cache = root / ".doro/native" / digest
    private_directory(cache)
    app = cache / "DoroChat.app"
    contents = app / "Contents"
    binaries = contents / "MacOS"
    for directory in (app, contents, binaries):
        private_directory(directory)
    binary = binaries / "DoroChat"
    if binary.is_symlink():
        raise DoroError("Native chat executable symlinks are not allowed")
    identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:10]
    info = {"CFBundleIdentifier": f"local.doro.collaboration-chat.build{identity}{digest}", "CFBundleExecutable": "DoroChat",
            "CFBundleName": "도로 협업 대화", "CFBundleVersion": "1", "CFBundlePackageType": "APPL",
            "LSUIElement": True, "NSHighResolutionCapable": True}
    path = contents / "Info.plist"
    path.write_bytes(plistlib.dumps(info))
    path.chmod(0o600)
    if binary.is_file():
        return app
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV}
    try:
        result = subprocess.run(["xcrun", "swiftc", *sdk, "-swift-version", "6", "-warnings-as-errors",
                                 *map(str, sources), "-o", str(binary)], env=env, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise DoroError("Native chat build timed out; no viewer or model was started") from error
    if result.returncode:
        raise DoroError("Native chat build failed: " + result.stderr[-4000:])
    binary.chmod(0o700)
    return app


def launch_viewer(root: Path, session_id: str, config_path: Path, display: str = "panel", *,
                  show_tasks: bool = False) -> dict[str, object]:
    session_key(session_id)
    app = viewer_app(root)
    logs = root / ".doro/native"
    private_directory(logs)
    log = logs / (session_id + ".log")
    command = [str(app / "Contents/MacOS/DoroChat"), sys.executable, str(root / "doro"),
               "--config", str(config_path.resolve()), "chat", session_id, "--json"]
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV}
    store = LocalStore(root / ".doro")
    state = PetSwapLedger(store).current()
    if display == "integrated" and (state is None or state.stage != "active" or session_id not in state.sessions):
        raise DoroError("Confirm the official pet swap first; chat --display panel keeps the original pet")
    if display == "integrated":
        sprite = Path.home() / ".codex/pets/dororong/spritesheet.webp"
        if not sprite.is_file() or sprite.is_symlink() or sprite.stat().st_size > 20_000_000:
            raise DoroError("The local Doro v2 sprite is missing or invalid; original assets were not changed")
        env["DORO_CHAT_PET_SPRITE"] = str(sprite)
    with viewer_lock(root) as lock:
        request = write_request(store, session_id, display, show_tasks=show_tasks)
        env["DORO_CHAT_REQUEST"] = str(request.path)
        if lock is None:
            wait_for_ack(request)
            return {"reused": True, "session_id": session_id, "display": display,
                    "model_calls": 0, "web_server": False}
        if display in {"hidden", "stop"}:
            return {"reused": lock is None, "session_id": session_id, "display": display,
                    "model_calls": 0, "web_server": False}
        env["DORO_CHAT_LOCK_FD"] = str(lock)
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=output, start_new_session=True, pass_fds=(lock,))
        wait_for_ack(request)
    return {"viewer_pid": process.pid, "app_path": str(app), "session_id": session_id, "display": display,
            "web_server": False, "model_calls": 0, "reused": False}
