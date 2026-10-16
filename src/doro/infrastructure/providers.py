from pathlib import Path
from collections.abc import Callable
import json
import os
import shutil

from doro.domain.models import Config, DoroError, Reply
from doro.infrastructure.process import execute
from doro.infrastructure.agy_public import AGENT, run_public
from doro.infrastructure.protocol import decode_reply
from doro.infrastructure.streaming import ClaudeTextStream

CODEX_SETTINGS = (
    'approval_policy="never"', 'web_search="disabled"', 'project_doc_max_bytes=0',
    'features.shell_tool=false', 'features.apps=false', 'features.plugins=false',
    'features.hooks=false', 'features.multi_agent=false', 'features.multi_agent_v2=false',
    'features.skill_search=false', 'features.skip_host_skill_discovery=true',
    'memories.generate_memories=false', 'memories.use_memories=false',
    'shell_environment_policy.inherit="none"',
    'skills.max_context_tokens=1',
)


def build_command(config: Config, name: str) -> list[str]:
    provider = config.providers[name]
    if not provider.enabled:
        raise DoroError(f"{name} is disabled; no detection or execution is permitted")
    argv = list(provider.command)
    if name == "codex":
        argv += ["exec", "--json", "--ephemeral", "--ignore-user-config", "--sandbox", "read-only",
                 "--skip-git-repo-check", "--color", "never"]
        for setting in CODEX_SETTINGS:
            argv += ["-c", setting]
        if provider.effort:
            argv += ["-c", f'model_reasoning_effort="{provider.effort}"']
        argv += ["-"]
    elif name == "claude":
        argv += ["--print", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                 "--safe-mode", "--restricted", "--tools", "",
                 "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                 "--permission-mode", "dontAsk", "--permission-prompts", "none",
                 "--settings", '{"disableAllHooks":true}', "--disable-slash-commands",
                 "--no-chrome", "--no-session-persistence", "--max-turns", "1",
                 "--max-budget-usd", str(config.limits.claude_call_usd)]
        if provider.effort:
            argv += ["--effort", provider.effort]
    else:
        argv += ["--sandbox", "--output-format", "stream-json", "--input-format", "stream-json",
                 "--disable-slash-commands", "--agent", AGENT, "--new-project",
                 "--print-timeout", f"{config.limits.timeout_seconds}s"]
        if provider.effort:
            argv += ["--effort", provider.effort]
    if provider.model:
        argv += ["--model", provider.model]
    return argv


class CliRunner:
    def __init__(self, config: Config, keep_running: Callable[[], bool] | None = None) -> None:
        self.config = config
        self.keep_running = keep_running

    def call(self, name: str, prompt: str, cwd: Path, timeout: float,
             on_text: Callable[[str], None] | None = None) -> Reply:
        argv = build_command(self.config, name)  # Disabled gate precedes even PATH lookup.
        if not shutil.which(argv[0]):
            raise DoroError(f"{name} CLI is not installed on PATH")
        if name == "agy":
            result = run_public(argv, prompt, self.config.providers[name].model, Path(argv[0]).parent.parent,
                                timeout, self.config.limits.max_process_bytes, self.keep_running)
            return decode_reply(name, result)
        if name == "codex":
            instructions = cwd / "codex-system.md"
            descriptor = os.open(instructions, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(self.config.roles[name])
            argv += ["-c", "model_instructions_file=" + json.dumps(str(instructions))]
        stream = ClaudeTextStream(on_text) if name == "claude" and on_text is not None else None
        result = execute(argv, prompt, cwd, timeout, self.config.limits.max_process_bytes,
                         stream.feed if stream is not None else None, self.keep_running)
        if stream is not None:
            stream.finish()
        return decode_reply(name, result)
