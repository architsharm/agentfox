# AgentFox for Codex CLI

Two separate things, and you probably want both:

1. **Governance hooks** put AgentFox in front of what Codex does on your machine: every
   prompt you submit, every shell command and file edit before it runs, every MCP call,
   and every tool result as it comes back. Same engine, same `coding-agent` policy pack and
   the same decision records as the Claude Code hooks. Installed with one CLI command; no
   plugin needed.
2. **This plugin** packages the AgentFox operator skills, the read-only MCP server and a
   safety hook, so Codex can run AgentFox for you (onboard a codebase, triage findings,
   author policy, export evidence) without enforcing anything you did not ask for.

AgentFox must be installed where Codex runs, and `agentfox` must be on the `PATH` Codex
starts hooks with:

```bash
pip install "git+https://github.com/architsharm/agentfox.git"
```

## 1. Govern Codex with hooks

```bash
agentfox admin hooks install --harness codex --agent codex-dev          # dry run: shows the file
agentfox admin hooks install --harness codex --agent codex-dev --write  # writes .codex/hooks.json
agentfox admin hooks daemon                                             # keep it running
```

`--write` merges three hooks into `.codex/hooks.json` (`--scope user` for
`$CODEX_HOME/hooks.json`, every project). It keeps everything already in the file, keeps the
previous file as `hooks.json.bak`, does nothing on a second run, refuses a file that is not
JSON, and does not add an event you already wired to `agentfox hooks run` inline in
`config.toml`. It also registers `codex-dev` (development, framework `codex`), grants Codex's
built-in tools (`Bash`, `apply_patch`, `view_image`, `update_plan`, `spawn_agent`) and binds the
`coding-agent` pack to it in observe.

**Then trust the hooks.** Codex skips a hook nobody has reviewed. Open Codex in the project,
run `/hooks`, and trust the three AgentFox entries; changing the file means trusting them
again. Codex also loads a project's `.codex/` layer only when the project is trusted.

### What is governed

| Codex surface | Hook | What AgentFox can do |
|---|---|---|
| Shell commands (every path: `shell`, `exec_command`, unified exec) | `PreToolUse` on `Bash` | Refuse before it runs, or rewrite the command |
| File edits (`apply_patch`) | `PreToolUse` on `apply_patch` | Refuse before the patch is applied; the patch is judged as an edit with its file list, not as a shell command |
| MCP tools | `PreToolUse` on `mcp__<server>__<tool>` | Refuse, or rewrite the arguments; ungranted tools are refused by default deny |
| Your prompt | `UserPromptSubmit` | Refuse the turn before the model sees it |
| Tool results | `PostToolUse` | Record; when a refused result arrives, Codex replaces it with the reason, so the model never reads it. The tool has already run |
| Hosted tools (web search) | none | Not governed: they run on OpenAI's side and never reach a hook |
| Holding a call for a person | none | Codex cannot ask from a hook, so a call AgentFox would hold is refused with the reason. Codex's own `approval_policy` prompts still apply |
| Anything outside Codex, or Codex with hooks disabled, untrusted, or bypassed | none | Not governed |

The hook is a guardrail on one machine, not a boundary. Codex's own docs say the same of
tool hooks: some specialised tool paths can opt out. If the daemon is down, each call is
let through and reported as unchecked on stderr.

### Evidence

Codex's hook contract here was read in its source (release 0.162.0: the output parser and
its own hook integration tests), not yet probed against a running Codex.
`agentfox admin hooks status` lists each row as `SOURCE 0.162.0`. Things the source settles
that a Claude Code hook gets wrong on Codex: an explicit `permissionDecision: "allow"` and
any `"ask"` are rejected as unsupported and the call runs, so AgentFox sends an empty reply
to allow and a deny where it would ask.

## 2. Install this plugin

```bash
codex plugin marketplace add architsharm/agentfox
codex plugin add agentfox@agentfox
```

From a clone, add `./plugins/codex` as a local marketplace instead. Then trust its hook
with `/hooks`.

- **Skills**: the same procedures as the Claude Code plugin (`skills/`, copied from
  `plugins/shared/`). Start with `using-agentfox`.
- **MCP server**: `agentfox mcp serve`, the read-only analysis tools. Nothing there decides,
  applies or rolls back a change.
- **Safety hook**: any `agentfox` command that changes what is blocked or granted
  (`policy enforce`, `permit grant`, `agents kill`, `proposals apply`, …) is refused when
  Codex tries to run it, with the reason and a request to hand the command to you. Claude
  Code asks you instead; Codex cannot ask from a hook.

`AGENTS.md`, `skills/`, `reference/` and `scripts/` are copies of `plugins/shared/`; edit the
originals and run `uv run python scripts/check/plugins.py --write`.
