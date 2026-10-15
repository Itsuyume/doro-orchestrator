import math

from doro.domain.models import DoroError, Task


def mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise DoroError(f"{name}: an object with string keys is required")
    return {str(k): v for k, v in value.items()}


def keys(value: dict[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise DoroError(f"{name}: invalid fields; expected {sorted(expected)}")


def string(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise DoroError(f"{name}: a non-empty string is required")
    return value


def integer(value: object, name: str, low: int = 1, high: int = 1_000_000) -> int:
    if type(value) is not int or not low <= value <= high:
        raise DoroError(f"{name}: an integer in [{low}, {high}] is required")
    return value


def number(value: object, name: str, *, low: float = 0.0) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DoroError(f"{name}: a finite number is required")
    result = float(value)
    if not math.isfinite(result) or result < low:
        raise DoroError(f"{name}: a finite number >= {low} is required")
    return result


def boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise DoroError(f"{name}: a boolean is required")
    return value


def strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise DoroError(f"{name}: a non-empty list is required")
    result = tuple(string(v, name) for v in value)
    if len(set(result)) != len(result):
        raise DoroError(f"{name}: duplicates are not allowed")
    return result


def parse_task(value: object) -> Task:
    data = mapping(value, "task")
    keys(data, {"message", "classification", "allowed_providers", "context"}, "task")
    task = Task(string(data["message"], "message"),
                string(data["classification"], "classification"),
                strings(data["allowed_providers"], "allowed_providers"),
                string(data["context"], "context", empty=True))
    if task.classification != "public":
        raise DoroError("Only explicitly classified public input may be shared")
    if set(task.allowed_providers) - {"codex", "claude", "agy"}:
        raise DoroError("Unknown provider in task allowlist")
    return task
