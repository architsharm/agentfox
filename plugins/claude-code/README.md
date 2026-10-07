# AgentFox plugin for Claude Code

The operator plugin for the AgentFox control plane. It packages the product's knowledge as
**skills, commands, subagents and safety hooks**, so a person can say "get my support agent
governed" or "get me ready for the SOC 2 audit" and a coding agent can do it correctly.
Without it, they'd have to learn 13 CLI commands and their subcommands, 200+ API routes and
40-odd docs pages first.

## Install

**Claude Code, from GitHub:**

```bash
claude plugin marketplace add architsharm/agentfox
```

```bash
claude plugin install agentfox@agentfox
```

**Claude Code, from a local clone (no install, for trying it or developing it):**

```bash
claude --plugin-dir ./plugins/claude-code
```

**Any other agent (Codex, Cursor, Gemini CLI, Aider, …).** Point it at
[`plugins/shared/AGENTS.md`](../shared/AGENTS.md), the runtime-neutral copy of this plugin's
rules, skills and reference. Everything is plain markdown with relative links, and the skills
follow the `SKILL.md` folder convention.

The plugin drives the `agentfox` CLI, so the product has to be installed where the agent
runs:

```bash
pip install "git+https://github.com/architsharm/agentfox.git"
```

## What you get

| Type the command | What happens |
|---|---|
| `/agentfox:tour` | Safe, offline tour of the product in a scratch database |
| `/agentfox:start [path]` | Scan your code, add `agentfox.auto()` in observe mode, show what it sees |
| `/agentfox:status` | Read-only posture: doctor, open findings, policy modes, agent states |
| `/agentfox:findings [severity]` | Grouped triage with a recommended action for each finding |
| `/agentfox:policy <what you want>` | Draft, validate, lint and simulate a policy; promotion only on your say-so |
| `/agentfox:guardrail "<business rule>"` | Plain English → an executable business guardrail, in observe mode |
| `/agentfox:gate [suite]` | Eval regression gate and a CI workflow for your repo |
| `/agentfox:redteam <agent>` | Adversarial probes, results explained, fixes proposed |
| `/agentfox:evidence [agent]` | Verify the audit chain and export an auditor-ready package |
| `/agentfox:contain <agent> [reason]` | Incident response: quarantine (with confirmation), blast radius, evidence |
| `/agentfox:proposals [id or status]` | Review what the improvement loop wants to change; applying anything needs your say-so |
| `/agentfox:plugin-check` | Check the plugin against the live CLI and repo (for maintainers) |

**MCP server.** The plugin also starts the MCP server (its `.mcp.json` uses the older
spelling `agentfox mcp serve`, an alias of `agentfox serve mcp`), which gives any MCP client 27
read-only tools: posture, findings and how often each one has recurred, the improvement
loop's change proposals, policy validate and simulate, guard a piece of text, analyse a
SQL/shell/HTTP action, audit verify, compliance status, guardrail tests and more. Nothing
there decides, applies or rolls back a change. Other MCP clients can run it directly:

```bash
agentfox serve mcp
```

Subagents (the model delegates to them, or you ask for one by name):

- **governance-auditor**: a read-only posture review that ends in a written report.
- **policy-author**: drafts and simulates policy. It never promotes one.
- **integration-engineer**: wires guardrails into your code in observe mode.

The **safety hook** turns every command that changes what gets blocked into a permission
prompt with a plain-language reason. That covers `policy enforce`, `agents kill`, `demo`,
`proposals apply`, `proposals rollback`, `--mode enforce` and `--submit`.

## How it's organised

See [STRUCTURE.md](../STRUCTURE.md): four layers of markdown, one home per fact, and a drift
checker that keeps it honest. `AGENTS.md`, `skills/` and `reference/` here are copies of
`plugins/shared/`, because an installed Claude Code plugin cannot read files outside its own
directory; edit the shared originals, then refresh the copies:

```bash
uv run python scripts/check/plugins.py --write
```
