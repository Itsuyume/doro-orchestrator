from dataclasses import replace

from doro.domain.models import Config, DoroError

MODELS = (("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5-5", "Sonnet 5.5"),
          ("claude-haiku-5-5", "Haiku 5.5"), ("", "Claude Code 기본값"))
EFFORTS = (("low", "낮음"), ("medium", "보통"), ("high", "높음"), ("xhigh", "매우 높음"), ("max", "최대"))


def validate_selection(model: str, effort: str) -> None:
    if model not in dict(MODELS) or effort not in dict(EFFORTS):
        raise DoroError("Unsupported model or effort; no setting or model call was changed")


def selected_config(config: Config, model: str, effort: str) -> Config:
    validate_selection(model, effort)
    providers = {**config.providers, "claude": replace(config.providers["claude"], model=model, effort=effort)}
    # A local next-call preference does not alter roles, permissions, budgets, or the approved session scope.
    return replace(config, providers=providers)
