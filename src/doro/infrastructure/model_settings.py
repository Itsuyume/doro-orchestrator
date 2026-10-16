from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from doro.domain.model_selection import AGY_EFFORTS, AGY_MODELS, EFFORTS, MODELS, selected_config, validate_selection
from doro.domain.model_preferences import ModelSelection
from doro.domain.models import Config, DoroError, Reply
from doro.infrastructure.agy_public import availability
from doro.infrastructure.input_store import authorize_ui
from doro.infrastructure.providers import CliRunner
from doro.infrastructure.storage import LocalStore, session_key


class ModelSettings:
    def __init__(self, store: LocalStore) -> None:
        self.store = store
        with store.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS model_choices (session_id TEXT PRIMARY KEY, model TEXT NOT NULL, effort TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS agy_choices (session_id TEXT PRIMARY KEY, model TEXT NOT NULL, effort TEXT NOT NULL, enabled INTEGER NOT NULL)")

    def choice(self, config: Config, session_id: str) -> tuple[str, str]:
        if session_id != "*":
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
        previous = next((turn.model for turn in reversed(session.turns) if turn.provider == "agy"), "")
        return ModelSelection(model, effort, actual, MODELS, EFFORTS, alternatives=(self.agy_view(session_id, previous),))

    def agy_view(self, session_id: str, actual_model: str = "") -> ModelSelection:
        model, effort, enabled = self.agy_choice(session_id)
        ready, reason = availability(self.store.root) if enabled else (False, "꺼져 있도로.")
        return ModelSelection(model, effort, actual_model, AGY_MODELS, AGY_EFFORTS, "agy", enabled, ready, reason)

    def agy_choice(self, session_id: str) -> tuple[str, str, bool]:
        if session_id != "*":
            session_key(session_id)
        with self.store.connect() as connection:
            row = connection.execute("SELECT model,effort,enabled FROM agy_choices WHERE session_id IN (?, '*') ORDER BY session_id='*' LIMIT 1",
                                     (session_id,)).fetchone()
        if row is None:
            return "gemini-4-argon", "medium", False
        model, effort, enabled = str(row[0]), str(row[1]), bool(row[2])
        validate_selection(model, effort, "agy")
        return model, effort, enabled

    def save_agy(self, model: str, effort: str, enabled: bool, session_id: str = "*", *, ui_token: str | None = None) -> None:
        validate_selection(model, effort, "agy")
        if type(enabled) is not bool:
            raise DoroError("AGY enabled must be a boolean")
        if session_id != "*":
            self.store.load(session_key(session_id))
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if ui_token is not None:
                authorize_ui(connection, session_id, ui_token)
            connection.execute("INSERT INTO agy_choices VALUES (?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET model=excluded.model,effort=excluded.effort,enabled=excluded.enabled",
                               (session_id, model, effort, int(enabled)))

    def work_config(self, config: Config, session_id: str) -> Config:
        model, effort, enabled = self.agy_choice(session_id)
        selected = selected_config(config, model, effort, "agy")
        agy = replace(selected.providers["agy"], enabled=enabled, command=(str(self.store.root / "bin/agy"),))
        return replace(selected, providers={**selected.providers, "agy": agy})


class SelectedAdvisorRunner:
    """Snapshot the next-call choice inside the existing Work execution lock."""
    def __init__(self, config: Config, settings: ModelSettings, session_id: str,
                 keep_running: Callable[[], bool] | None = None) -> None:
        self.config, self.settings, self.session_id = config, settings, session_id
        self.keep_running = keep_running

    def call(self, name: str, prompt: str, cwd: Path, timeout: float,
             on_text: Callable[[str], None] | None = None) -> Reply:
        if name not in {"claude", "agy"}:
            raise DoroError("Only explicitly approved external advisors can run")
        config = self.settings.work_config(self.config, self.session_id)
        if name == "claude":
            config = selected_config(config, *self.settings.choice(config, self.session_id))
        reply = CliRunner(config, self.keep_running).call(name, prompt, cwd, timeout, on_text)
        expected = config.providers[name].model
        if expected and reply.model != expected:
            raise DoroError(f"Requested model {expected}, actual {reply.model or 'unknown'}; response not adopted")
        return reply
