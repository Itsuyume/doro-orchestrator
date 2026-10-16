"""Install a model-free change detector. Never schedules unconditional Work turns."""
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tomllib
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
LABEL = "local.doro.shared-radar"


def binary(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise ValueError(name + " is required before installing the detector")
    return str(Path(found).resolve())


def stop_existing(domain: str) -> None:
    check = subprocess.run(["launchctl", "print", domain + "/" + LABEL], capture_output=True, text=True)
    if check.returncode == 0:
        subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], check=True)
    elif "Could not find service" not in check.stderr:
        raise ValueError("Unable to inspect existing detector service: " + check.stderr.strip())


def install(connection: Path, automation: Path, user: Path) -> dict[str, str]:
    connection, automation = connection.resolve(strict=True), automation.resolve(strict=True)
    owner = tomllib.loads(automation.read_text())["target_thread_id"]
    base = user / ".codex/automations/space/detector"
    agents = user / "Library/LaunchAgents"
    plist = agents / (LABEL + ".plist")
    if any(path.is_symlink() for path in (base, agents, plist)):
        raise ValueError("Detector installation paths cannot be symlinks")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base.chmod(0o700)
    config = base / "config.json"
    if config.exists():
        old = json.loads(config.read_text())
        if old["connection"] != str(connection) or old["owner"] != owner:
            raise ValueError("An existing detector has another scope or owner; refusing to redirect it")
    domain = "gui/" + str(os.getuid())
    stop_existing(domain)
    archive = base.parent / "detector-archives" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    for path in (config, plist, base / "runtime"):
        if path.exists():
            archive.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = archive / path.name
            shutil.copytree(path, target) if path.is_dir() else shutil.copy2(path, target)
    runtime = base / "runtime"
    candidate = base / (".runtime-" + uuid4().hex)
    shutil.copytree(ROOT / "src", candidate / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if runtime.exists():
        shutil.rmtree(runtime)
    candidate.rename(runtime)
    settings = {"version": 1, "enabled": True, "connection": str(connection), "automation": str(automation),
                "state_root": str(base / "state"), "codex": binary("codex"), "obsidian": binary("obsidian"),
                "owner": owner, "remote_seconds": 1800}
    config.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    config.chmod(0o600)
    agents.mkdir(parents=True, exist_ok=True)
    arguments = [str(Path(sys.executable).resolve()), "-m", "doro.interface.shared_radar", "--config", str(config),
                 "--report", str(base / "status.json")]
    job = {"Label": LABEL, "ProgramArguments": arguments, "WorkingDirectory": str(base),
           "EnvironmentVariables": {"PYTHONPATH": str(runtime / "src"), "PATH": os.environ.get("PATH", os.defpath)},
           "RunAtLoad": True, "StartInterval": 60, "ProcessType": "Background",
           "StandardOutPath": "/dev/null", "StandardErrorPath": str(base / "errors.log")}
    plist.write_bytes(plistlib.dumps(job))
    plist.chmod(0o600)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    return {"configuration": str(config), "service": str(plist), "runtime": str(runtime), "status": str(base / "status.json")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", type=Path, required=True)
    parser.add_argument("--automation", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.connection, args.automation, Path.home()), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
