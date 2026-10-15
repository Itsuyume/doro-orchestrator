"""Build one local launcher. Opening it never creates a Work chat or calls a model."""
from pathlib import Path
import json
import plistlib
import subprocess
import sys

from tools.install_work_skill import install

ROOT = Path(__file__).resolve().parents[1]

IDENTITY = "local.doro.window-open"


def create_app(user_directory: Path, project: Path = ROOT) -> Path:
    app = user_directory / "Applications" / "도로협업.app"
    info = app / "Contents/Info.plist"
    binaries = app / "Contents/MacOS"
    target = binaries / "DoroOpen"
    if any(path.is_symlink() for path in (app, app / "Contents", info, binaries, target)):
        raise ValueError("Launcher symlinks are not allowed")
    if app.exists() and (not info.is_file() or plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") != IDENTITY):
        raise ValueError("A different application already uses this name; no files were overwritten")
    prepared = subprocess.run([sys.executable, str(project / "doro"), "window", "prepare"],
                              check=True, capture_output=True, text=True)
    packet = json.loads(prepared.stdout)
    sdk = packet["sdk"]
    if not isinstance(sdk, list) or not all(isinstance(value, str) for value in sdk):
        raise ValueError("Invalid SDK arguments from the local viewer builder")
    binaries.mkdir(parents=True, exist_ok=True)
    subprocess.run(["xcrun", "swiftc", *sdk, "-swift-version", "6", "-warnings-as-errors",
                    str(project / "native/DoroOpen/main.swift"), "-o", str(target)], check=True)
    target.chmod(0o700)
    info.write_bytes(plistlib.dumps({"CFBundleIdentifier": IDENTITY, "CFBundleExecutable": "DoroOpen",
        "CFBundleName": "도로협업", "CFBundleDisplayName": "도로협업", "CFBundleVersion": "1",
        "CFBundlePackageType": "APPL", "LSUIElement": True, "NSHighResolutionCapable": True}))
    return app


if __name__ == "__main__":
    install(Path.home())
    print(create_app(Path.home()))
