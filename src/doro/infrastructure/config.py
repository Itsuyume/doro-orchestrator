import hashlib
from pathlib import Path
import tomllib

from doro.domain.models import Config, DoroError, Limits, Provider
from doro.domain.policy import plan_turns
from doro.domain.validation import boolean, integer, keys, mapping, number, string, strings


def parse_provider(value: object) -> Provider:
    data = mapping(value, "provider")
    keys(data, {"enabled", "command", "model", "effort", "max_calls"}, "provider")
    return Provider(boolean(data["enabled"], "enabled"), strings(data["command"], "command"),
                    string(data["model"], "model", empty=True),
                    string(data["effort"], "effort", empty=True),
                    integer(data["max_calls"], "max_calls", high=20))


def parse_limits(value: object) -> Limits:
    data = mapping(value, "limits")
    keys(data, set(Limits.__dataclass_fields__), "limits")
    return Limits(
        integer(data["debate_rounds"], "debate_rounds", high=3),
        integer(data["max_calls"], "max_calls", high=20),
        integer(data["daily_calls"], "daily_calls", high=100),
        integer(data["timeout_seconds"], "timeout_seconds", high=300),
        integer(data["session_seconds"], "session_seconds", high=1800),
        integer(data["max_prompt_chars"], "max_prompt_chars", high=100_000),
        integer(data["max_response_chars"], "max_response_chars", high=50_000),
        integer(data["max_process_bytes"], "max_process_bytes", high=4_000_000),
        integer(data["max_tokens"], "max_tokens", high=200_000),
        number(data["claude_call_usd"], "claude_call_usd", low=0.01),
        number(data["session_reported_usd"], "session_reported_usd", low=0.01),
    )


def load_config(path: Path, roles_directory: Path | None = None) -> Config:
    raw = path.read_bytes()
    data = mapping(tomllib.loads(raw.decode()), "config")
    keys(data, {"version", "providers", "limits"}, "config")
    if integer(data["version"], "version") != 1:
        raise DoroError("Unsupported config version")
    entries = mapping(data["providers"], "providers")
    keys(entries, {"codex", "claude", "agy"}, "providers")
    providers = {name: parse_provider(value) for name, value in entries.items()}
    if not providers["codex"].enabled or not providers["claude"].enabled:
        raise DoroError("Codex and Claude must both be enabled; no silent fallback")
    limits = parse_limits(data["limits"])
    directory = roles_directory if roles_directory is not None else path.parent / "roles"
    roles = {name: (directory / f"{name}.md").read_text() for name in providers}
    fingerprint = hashlib.sha256(raw + "\n".join(roles.values()).encode()).hexdigest()
    config = Config(providers, limits, fingerprint, roles)
    turns = plan_turns(config.participants(), limits.debate_rounds)
    if len(turns) > limits.max_calls:
        raise DoroError("Configured turn plan exceeds the session call limit")
    for name, provider in providers.items():
        if sum(turn.provider == name for turn in turns) > provider.max_calls:
            raise DoroError(f"Configured turn plan exceeds {name}'s call limit")
    if limits.max_response_chars >= limits.max_prompt_chars:
        raise DoroError("Response bound must be smaller than prompt bound")
    return config
