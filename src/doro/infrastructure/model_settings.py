from collections.abc import Callable
from pathlib import Path

from doro.domain.model_selection import EFFORTS, MODELS, selected_config, validate_selection
from doro.domain.models import Config, DoroError, ModelSelection, Reply
from doro.infrastructure.input_store import authorize_ui
from doro.infrastructure.providers import CliRunner
from doro.infrastructure.storage import LocalStore, session_key


class ModelSettings:
    def __init__(self, store: LocalStore) -> None:
        self.store = store
        with store.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS model_choices (session_id TEXT PRIMARY KEY, model TEXT NOT NULL, effort TEXT NOT NULL)")

    def choice(self, config: Config, session_id: str) -> tuple[str, str]:
        session_key(session_id)
        with self.store.connect() as connection:
            row = connection.execute("SELECT model,effort FROM model_choices WHERE session_id IN (?, '*') ORDER BY session_id='*' LIMIT 1",
                                     (session_id,)).fetchone()
        if row is None:
            provider = config.providers["claude"]
            return provider.model, provider.effort or "medium"
        model, effort = str(row[0]), str(row[1])
        validate_selection(model, effort)
        return model, effort

    def save(self, model: str, effort: str, session_id: str = "*", *, ui_token: str | None = None) -> None:
        validate_selection(model, effort)
        if session_id != "*":
            self.store.load(session_key(session_id))
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if ui_token is not None:
                authorize_ui(connection, session_id, ui_token)
            connection.execute("INSERT INTO model_choices VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET model=excluded.model,effort=excluded.effort",
                               (session_id, model, effort))

    def view(self, config: Config, session_id: str) -> ModelSelection:
        model, effort = self.choice(config, session_id)
        session = self.store.load(session_id)
        actual = next((turn.model for turn in reversed(session.turns) if turn.provider == "claude"), "")
        return ModelSelection(model, effort, actual, MODELS, EFFORTS)


class SelectedClaudeRunner:
    """Snapshot the next-call choice inside the existing Work execution lock."""
    def __init__(self, config: Config, settings: ModelSettings, session_id: str) -> None:
        self.config, self.settings, self.session_id = config, settings, session_id

    def call(self, name: str, prompt: str, cwd: Path, timeout: float,
             on_text: Callable[[str], None] | None = None) -> Reply:
        if name != "claude":
            raise DoroError("The Work model selector only controls Claude")
        choice = self.settings.choice(self.config, self.session_id)
        reply = CliRunner(selected_config(self.config, *choice)).call(name, prompt, cwd, timeout, on_text)
        if choice[0] and reply.model != choice[0]:
            raise DoroError(f"Requested model {choice[0]}, actual {reply.model or 'unknown'}; response not adopted")
        return reply
