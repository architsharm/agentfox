"""Harbor agent: Harbor's own Claude Code agent with the AgentFox hook installed.

The only difference from the stock ``claude-code`` agent is the hook. The model,
flags, Claude Code version and prompt are identical, so the stock agent is the
baseline arm and this is the treatment arm.

The hook runs inside the task container from a copy of ``src/agentfox`` on the
container's own ``python3``. The hook path is standard library only, so nothing is
installed. A container without ``python3`` runs the hook as a no-op, which is the
baseline behaviour, and ``hook-missing`` in the agent log says so.

Mode is ``AGENTFOX_DELIVERY=only``: the delivery policies, without the control-plane
daemon (there is none in a task container). Per-session state is written under
``/logs/agent/agentfox-delivery/``, which Harbor copies back with the trial, so every
intervention can be audited afterwards.

Run (from the repo root):

    PYTHONPATH=benchmarks/terminal_bench harbor run \\
        --agent agentfox_claude:AgentFoxClaudeCode -m anthropic/claude-sonnet-5-5 ...
"""

from __future__ import annotations

import json
import shlex
import shutil
import tempfile
from pathlib import Path

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "src" / "agentfox"
REMOTE = "/opt/agentfox-src"
STATE = (EnvironmentPaths.agent_dir / "agentfox-delivery").as_posix()

HOOK_SCRIPT = f"""\
import sys
sys.path.insert(0, {REMOTE!r})
from agentfox.hooks.run import run
out = run("claude", "terminal-bench", sys.stdin.read())
sys.stdout.write(out.stdout)
sys.stderr.write(out.stderr)
sys.exit(out.exit_code)
"""

#: Every event the delivery policies read. PostToolUse records what ran.
EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


def hook_command() -> str:
    env = f"AGENTFOX_DELIVERY=only AGENTFOX_DELIVERY_STATE={STATE}"
    return (
        f"if command -v python3 >/dev/null 2>&1; then {env} python3 {REMOTE}/hook.py; "
        f"else echo hook-missing >> {STATE}.missing; fi"
    )


def settings() -> dict:
    hook = [{"type": "command", "command": hook_command(), "timeout": 30}]
    return {
        "hooks": {
            event: [
                {"matcher": "*", "hooks": hook} if event.endswith("ToolUse") else {"hooks": hook}
            ]
            for event in EVENTS
        }
    }


class AgentFoxClaudeCode(ClaudeCode):
    @staticmethod
    def name() -> str:
        return "agentfox-claude-code"

    async def install(self, environment: BaseEnvironment) -> None:
        await super().install(environment)
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "agentfox"
            shutil.copytree(SOURCE, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            await self.exec_as_root(environment, command=f"mkdir -p {REMOTE} && chmod 777 {REMOTE}")
            await environment.upload_dir(staged, f"{REMOTE}/agentfox")
        script = shlex.quote(HOOK_SCRIPT)
        await self.exec_as_root(
            environment,
            command=f"printf '%s' {script} > {REMOTE}/hook.py && chmod -R a+rX {REMOTE}",
        )

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        # Claude Code reads user settings from $CLAUDE_CONFIG_DIR, which the parent
        # sets to /logs/agent/sessions; its setup step only mkdirs, so writing first
        # is safe.
        config = (EnvironmentPaths.agent_dir / "sessions").as_posix()
        body = shlex.quote(json.dumps(settings(), indent=1))
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {config} {STATE} && printf '%s' {body} > {config}/settings.json",
        )
        await super().run(instruction, environment, context)
