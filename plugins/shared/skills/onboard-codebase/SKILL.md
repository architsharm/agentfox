---
name: onboard-codebase
description: Takes a user's agent codebase from ungoverned to observed. It scans for model calls, initialises AgentFox, adds agentfox.auto() in observe mode, generates first traffic, and reports what was found. Use when the user wants to "start using agentfox", "govern my agent", "add guardrails to this repo", or runs /agentfox:start.
---

# Onboard a codebase

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

End state: every model call in the user's process is traced, evaluated against policy and
written to the audit log, **in observe mode**. Nothing is blocked that wasn't blocked before.
The user gets a short report of what the product sees.

## 1. Preconditions

```bash
agentfox admin version
```

- **Exits 127:** install the package into the *project's* environment (its venv, uv project or
  poetry env), not globally. The install line is `pip install "git+https://github.com/architsharm/agentfox.git"`.
- **Separate database:** ask whether they want one per project. The default is a
  `agentfox.db` next to the package. For a project-local DB, export
  `AGENTFOX_DATABASE_URL=sqlite:///$PWD/.agentfox/agentfox.db` and add `.agentfox/` to
  `.gitignore`.
- **Config file:** `init` writes `agentfox.toml` in the project, and every process started in
  that directory reads it. Environment variables still win. Tell the user it's live config,
  not documentation.

## 2. Initialise (idempotent)

```bash
agentfox init
```

`init` lists each policy pack with its mode. Make sure the user reads it:
`baseline` and `eu-ai-act-high-risk` start in observe, but **`tool-containment` enforces from
the start**. It escalates or blocks irreversible tool calls with untrusted arguments, denied
capabilities, runaway loops and destructive cascades.

## 3. Find what talks to a model

```bash
agentfox scan . --json
```

From the JSON, list the ungoverned call sites (file:line, library) and the entry points. If
there are many, group them by entry point, because one `auto()` per process covers
everything the process imports.

## 4. Choose the integration surface

Use the decision table in [reference/sdk.md](../../reference/sdk.md). The default is
`agentfox.auto()`. Recommend more than that only when:

| Signal in their code | Recommend instead of, or on top of, `auto()` |
|---|---|
| async clients, `ainvoke`, streaming | gateway proxy (auto doesn't govern these) |
| tools with side effects (payments, SQL, email, tickets) | SDK `@nom.tool(..., impact=...)` — load **integrate-guardrails** |
| a LangGraph graph | `AgentFoxGuard` node wrappers |
| a FastAPI service taking prompts | `integrations.fastapi.install` + `guard()` |
| MCP servers | `McpGovernor` |

## 5. Add the one-liner

Put it at the top of each process entry point, before model clients are created:

```python
import agentfox
agentfox.auto(agent="<slug>")      # follows policy modes: baseline observes, so nothing new is blocked
```

Choose `<slug>` with the user: a stable, lowercase service name such as `support-triage`.
It can also come from `AGENTFOX_AGENT`. Show the diff. Don't pass `mode="enforce"`. The default
follows each policy's mode, so blocking starts only when someone runs `policy enforce`. A
killed or quarantined agent is refused under the default.

## 5b. Declare what the agent's tools can do

This is the step most teams skip and the one that matters most. Detection is probabilistic and
every published result says a determined attacker gets past it. What holds afterwards is what
the agent is *allowed to do*, and that is declared, not detected.

```bash
agentfox declare tool payments.refund --impact irreversible --triggers "ledger.write"
agentfox declare tool crm.lookup --impact read
agentfox declare list tools
```

Impact tiers are `read`, `write`, `high_impact`, `irreversible`. Get these right with the user,
tool by tool: an irreversible action recorded as `read` is one a tainted argument can reach.
`agentfox doctor` grades this directly under **containment**.

## 6. Generate first traffic

Run the thing the user already runs, such as their tests, a local script or the dev server,
and make one or two model calls. Offline, set `AGENTFOX_DEFAULT_PROVIDER=echo` only if their
code goes through the gateway. Otherwise their own provider handles the call as before.

## 7. Report

```bash
agentfox doctor --json
agentfox findings --json
agentfox agents list --json
```

Keep the report short:

- **Governed now:** which agents and how many calls.
- **Would have blocked:** any `effective_verdict` other than allow in the findings.
- **Containment readiness:** what `doctor` reports under `containment` and `data scope` — how
  many tools can act, how many grants exist, how many tables are row-scoped.
- **Doctor warnings that matter:** `authentication` outside development, fail-open, no
  knowledge boundary.
- **Not governed:** remaining call sites and why.

`doctor` exits 1 when any check is bad, with or without `--json`.

## 8. Recommend exactly one next step

Pick the one that matches what the report showed:

- A detection fired → **triage-findings**.
- The agent has side-effecting tools → **integrate-guardrails**.
- The agent answers questions from company data → **declare-agent-controls**.
- They want CI protection → **eval-gate**.
- Findings look right and they want to block → **author-policy** (simulate first).
