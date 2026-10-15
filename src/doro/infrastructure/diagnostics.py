import json
from pathlib import Path
import shutil
import tempfile

from doro.domain.models import Config, DoroError
from doro.domain.validation import mapping
from doro.infrastructure.process import execute


def probe(config: Config, name: str, cwd: Path) -> dict[str, object]:
    provider = config.providers[name]
    if not provider.enabled:
        return {"enabled": False, "checked": False, "reason": "disabled: never probed or executed"}
    executable = shutil.which(provider.command[0])
    if not executable:
        return {"enabled": True, "installed": False, "authenticated": False}
    version = execute([*provider.command, "--version"], "", cwd, 10, 10000)
    result: dict[str, object] = {"enabled": True, "installed": True,
                                "version": version.stdout.strip(), "executable": executable}
    if name == "agy":
        result.update({"authenticated": False, "reason": "AGY authentication requires a future explicit check"})
        return result
    auth_args = ["login", "status"] if name == "codex" else ["auth", "status"]
    auth = execute([*provider.command, *auth_args], "", cwd, 10, 10000)
    if name == "codex":
        ready = auth.returncode == 0 and "chatgpt" in (auth.stdout + auth.stderr).lower()
        method = "ChatGPT existing login" if ready else "not a verified ChatGPT login"
    else:
        data = mapping(json.loads(auth.stdout), "Claude auth status")
        ready = auth.returncode == 0 and data.get("loggedIn") is True and data.get("authMethod") == "claude.ai"
        method = "Claude existing subscription login" if ready else "not a verified Claude subscription login"
    result.update({"authenticated": ready, "auth_method": method})
    return result


def doctor(config: Config) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="doro-doctor-") as tmp:
        return {name: probe(config, name, Path(tmp)) for name in config.providers}


def require_auth(config: Config) -> None:
    result = doctor(config)
    for name, value in result.items():
        data = mapping(value, "diagnostics")
        if config.providers[name].enabled and data.get("authenticated") is not True:
            raise DoroError(f"{name}: existing subscription authentication is not ready; run doro doctor")
