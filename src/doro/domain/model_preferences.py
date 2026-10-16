from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSelection:
    model: str
    effort: str
    actual_model: str
    models: tuple[tuple[str, str], ...]
    efforts: tuple[tuple[str, str], ...]
    provider: str = "claude"
    enabled: bool = True
    ready: bool = True
    reason: str = ""
    alternatives: tuple["ModelSelection", ...] = ()
