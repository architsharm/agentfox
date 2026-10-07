---
title: How the operator plugins keep their markdown — the structure contract
layer: meta
audience: maintainers of this repo (human or agent)
---

# Plugin structure

The product has 43 markdown docs, a CLI of 13 commands, an HTTP API with 200+ routes and six SDK
surfaces. Nobody, human or agent, should need all of that at once. The operator plugins are
a **layered set of markdown files**. Each layer answers one kind of question, and each fact
has exactly one home.

"Plugin" here means AgentFox packaged for a coding agent so an operator can *use* AgentFox.
It is not a harness: in this repository a harness is a coding agent AgentFox *governs*
(`src/agentfox/harnesses/`).

```
plugins/
├── STRUCTURE.md                  this file: the contract every plugin file follows
├── shared/                       RUNTIME-NEUTRAL — the one home of everything below
│   ├── AGENTS.md             L3  router for ANY agent runtime: "user wants X → load skill Y" + golden rules
│   ├── reference/            L1  FACTS — dense, agent-optimised, verified against code
│   │   ├── cli.md                every command, flag, side effect, exit code
│   │   ├── config.md             every AGENTFOX_* variable and extra
│   │   ├── http-api.md           inline + control-plane routes, auth, outcomes
│   │   ├── sdk.md                auto(), SDK, LangGraph, FastAPI, MCP, proxy — and which to pick
│   │   ├── policy-schema.md      policy YAML: conditions, effects, precedence
│   │   ├── detectors-and-findings.md surfaces, detectors, verdicts, finding types and first moves
│   │   ├── known-issues.md       bugs and doc drift an agent must route around
│   │   ├── glossary.md           modes, terms, ID prefixes, commit conventions
│   │   └── docs-map.md           classifies every repo .md: canonical / generated / drifted / task / human-only
│   └── skills/               L2  PROCEDURES — one folder per job-to-be-done
│       ├── using-agentfox/SKILL.md   entry skill: sends the agent to AGENTS.md (plugins load skills, not root files)
│       └── <job>/SKILL.md        steps, decision points, safety gates; links to L1 for facts
│           └── templates/ | references/   material only this skill needs
└── claude-code/                  THE CLAUDE CODE PLUGIN (repo root holds marketplace.json → ./plugins/claude-code)
    ├── README.md                     for humans: what this is, how to install it, how to use it
    ├── .claude-plugin/plugin.json    Claude Code plugin manifest
    ├── .mcp.json             L3  MCP server: `agentfox mcp serve`, 27 read-only tools for any MCP client
    ├── AGENTS.md, reference/, skills/    COPIES of shared/, made by `scripts/check/plugins.py --write`
    ├── commands/             L3  ENTRY POINTS — what a user types (/agentfox:<name>), thin, call a skill
    ├── agents/               L3  ROLES — subagents with scoped tools (read-only auditor, policy author, …)
    ├── hooks/hooks.json      L4  GUARDRAILS FOR THE PLUGIN — confirmation gate on blocking commands
    └── scripts/              L4  launcher, hook implementation
```

**Why copies.** An installed Claude Code plugin cannot load a component outside its own
directory: a path such as `../shared/skills` is rejected, and only a git-hosted marketplace
dereferences symlinks (a `--plugin-dir` or local-path install skips them). So the Claude Code
plugin carries byte-for-byte copies of `shared/`, committed, and `scripts/check/plugins.py`
fails CI when a copy differs from its original. Edit `shared/`, never the copies, then run
`uv run python scripts/check/plugins.py --write`. A plugin for another agent runtime is a
sibling folder that gets the same copies (add it to `RUNTIMES` in the checker).

Layer 0 is the product's own docs (`docs/`, `benchmarks/`, READMEs). They stay where they
are and stay human-first. The plugins link to them through `reference/docs-map.md` and
never copies them.

## The rules

1. **One fact, one home.** A flag, env var, route or default lives in exactly one
   `reference/` file. Skills link to it; they don't restate it. The exception: a skill may
   show the exact command it wants run, because that is the procedure. The drift checker
   verifies those commands too.
2. **Code beats reference beats docs.** Each reference file names its `source_of_truth` in
   frontmatter. When they disagree, fix the reference file and, if the doc is wrong, record
   it in `reference/known-issues.md`.
3. **Procedures, not essays.** A `SKILL.md` is a numbered procedure with explicit decision
   points ("if X, do Y") and explicit stop-and-confirm gates. Keep it under ~150 lines. Move
   long material into the skill's own `references/` or `templates/`.
4. **Entry points are thin.** A command or agent file says *who* and *when*, then hands off
   to a skill. If a command file grows logic, that logic belongs in a skill.
5. **Safety is structural, not advisory.** Anything that changes whether traffic is blocked
   is (a) marked **BLK** in `reference/cli.md`, (b) gated in `hooks/hooks.json`, and (c) an
   explicit confirm step in every skill that reaches it. All three change together.
6. **Generated docs are regenerated, never edited.** `docs/status.md` and
   `docs/design/coverage-map.md` have commands in `reference/docs-map.md`.
7. **Same-commit rule.** A change to `src/agentfox/apps/cli/`, `config.py`, `apps/gateway/routes/`,
   `platform/policy/model.py` or `packs/*/policies/` updates the matching `reference/` file in the same
   commit. Fixing a bug in `known-issues.md` deletes its entry in the same commit.
8. **Every repo `.md` is classified.** A new doc anywhere in the repo gets a row in
   `reference/docs-map.md`.

**Why no `CLAUDE.md` in the plugin.** A plugin-root `CLAUDE.md` isn't loaded by Claude
Code, and `claude plugin validate` warns about it. The rules live in `AGENTS.md`, which any
agent runtime can read. The `using-agentfox` skill is how a plugin runtime reaches them.

**Commands in skills are written `agentfox …`.** The plugin may be installed anywhere, so
skills never hard-code a path to the launcher. `AGENTS.md` → "Running the CLI" is the one
place that explains the fallbacks.

## Frontmatter contract

| File type | Required frontmatter |
|---|---|
| `reference/*.md` | `title`, `layer: reference`, `audience`, `source_of_truth`, `verified_against` |
| `skills/*/SKILL.md` | `name` (= folder name), `description` (starts with what it does, then "Use when …") |
| `commands/*.md` | `description`, `argument-hint` if it takes arguments |
| `agents/*.md` | `name`, `description`, `tools` (least privilege) |

**The MCP server is read-only by construction.** It exposes analysis and inspection tools
only (`src/agentfox/apps/mcp_server.py`). Anything that changes enforcement, stops an agent,
decides or applies a change proposal, or sends data goes through the CLI, where the hook
asks first. Adding a state-changing MCP tool would bypass that gate, so don't. When you add
or remove a tool, update the count in `README.md`, `reference/cli.md` and this file.

## Keeping it honest

```bash
uv run python scripts/check/plugins.py
```

The checker loads the real Typer command tree and fails when any of these is true:

- A plugin file names an `agentfox` command or flag that doesn't exist.
- A plugin file links to a repo path that doesn't exist.
- A copy in `claude-code/` differs from its original in `shared/`.
- A skill, command or agent file is missing required frontmatter.
- A repo `.md` file is missing from `docs-map.md`.

It reads code only (inline spans and fenced blocks), never prose. A line that quotes a
phantom command on purpose, like the known-issues entries, must say "does not exist" on the
same line.

Run it before committing plugin changes, and after any CLI change. Also run
`claude plugin validate ./plugins/claude-code`.

## Adding things

- **A new skill.** Create `skills/<verb-noun>/SKILL.md` and add a routing row in `AGENTS.md`.
  If users will type it, add a command. Then run the checker.
- **A new CLI command.** Add a row to `reference/cli.md` with its side-effect tag. If it is
  BLK, add a pattern to `scripts/guard_blocking_commands.py` and a confirm step to the skill
  that uses it.
- **A new doc in `docs/`.** Classify it in `reference/docs-map.md`.
