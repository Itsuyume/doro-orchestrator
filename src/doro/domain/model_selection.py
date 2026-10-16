from dataclasses import replace

from doro.domain.models import Config, DoroError

MODELS = (("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5-5", "Sonnet 5.5"),
          ("claude-haiku-5-5", "Haiku 5.5"), ("", "Claude Code 기본값"))
EFFORTS = (("low", "낮음"), ("medium", "보통"), ("high", "높음"), ("xhigh", "매우 높음"), ("max", "최대"))
AGY_MODELS = (("gemini-4-argon", "Gemini 4 Argon"),)
AGY_EFFORTS = EFFORTS[:3]


def validate_selection(model: str, effort: str, provider: str = "claude") -> None:
    if provider not in {"claude", "agy"}:
        raise DoroError("Unknown advisory provider")
    models, efforts = (MODELS, EFFORTS) if provider == "claude" else (AGY_MODELS, AGY_EFFORTS)
    if model not in dict(models) or effort not in dict(efforts):
        raise DoroError("Unsupported model or effort; no setting or model call was changed")


def selected_config(config: Config, model: str, effort: str, provider: str = "claude") -> Config:
    validate_selection(model, effort, provider)
    resolved = f"{model}-{effort}" if provider == "agy" else model
    providers = {**config.providers, provider: replace(config.providers[provider], model=resolved, effort=effort)}
    # A local next-call preference does not alter roles, permissions, budgets, or the approved session scope.
    return replace(config, providers=providers)
