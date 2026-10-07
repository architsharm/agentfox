# AgentFox plugin — start here

You are operating the **AgentFox control plane**: governance, security and compliance for AI
agents in production. It discovers agents, enforces policy on their model and tool calls,
evaluates them, keeps a tamper-evident audit log and exports compliance evidence.

**The product's core claim, and the thing to lead with:** an agent cannot take an action it was
never entitled to take, even when the model is fooled. Detection is the weakest layer and is
published as such. Containment — capability grants, argument provenance, declared tool impacts —
is what still holds when a detector misses, and it is *declared*, so helping a user declare it
is the highest-value thing you can do for them.

This file is the router. Read it fully, then load **one** skill for the job at hand. Load
reference files only when a skill points you there. The layout is explained in
`plugins/STRUCTURE.md` in the AgentFox repository.

## Route the request

| The user wants to… | Load skill |
|---|---|
| (plugin runtimes) anything AgentFox — the entry skill that points back here | [skills/using-agentfox](skills/using-agentfox/SKILL.md) |
| see what this product does, quickly and safely | [skills/tour-product](skills/tour-product/SKILL.md) |
| start governing their own agent codebase | [skills/onboard-codebase](skills/onboard-codebase/SKILL.md) |
| wire guardrails into specific code (tools, LangGraph, FastAPI, MCP, proxy) | [skills/integrate-guardrails](skills/integrate-guardrails/SKILL.md) |
| understand what was found and what to do about it | [skills/triage-findings](skills/triage-findings/SKILL.md) |
| write, change, simulate or promote a policy | [skills/author-policy](skills/author-policy/SKILL.md) |
| turn a written business rule ("refunds over $500 need a manager") into a guardrail | [skills/business-guardrails](skills/business-guardrails/SKILL.md) |
| stop wrong answers, stale sources, over-sharing, missed human handoffs | [skills/declare-agent-controls](skills/declare-agent-controls/SKILL.md) |
| block regressions in CI | [skills/eval-gate](skills/eval-gate/SKILL.md) |
| attack their own agent before someone else does | [skills/red-team](skills/red-team/SKILL.md) |
| prepare for an audit, export evidence, check framework posture | [skills/audit-evidence](skills/audit-evidence/SKILL.md) |
| respond to an agent misbehaving right now | [skills/incident-response](skills/incident-response/SKILL.md) |
| review what the improvement loop wants to change, and decide it | [skills/operate-improvement-loop](skills/operate-improvement-loop/SKILL.md) |
| run it as a service: serve, deploy, harden auth, upgrade | [skills/operate-deployment](skills/operate-deployment/SKILL.md) |
| change the AgentFox codebase itself | [skills/develop-agentfox](skills/develop-agentfox/SKILL.md) |

If nothing fits, answer from [reference/](reference/). If the question is about *why* the
product is shaped the way it is, [reference/docs-map.md](reference/docs-map.md) says which
doc to open.

## Golden rules

1. **Observe before enforce.** Everything starts in observe mode. Never run a **BLK**
   command (see [reference/cli.md](reference/cli.md)) unless the user asked for exactly that
   outcome in this conversation. The plugin's safety hook will ask them. Let it, and don't
   work around it.
2. **Use a scratch database for demos and experiments.** Prefix commands with
   `AGENTFOX_DATABASE_URL=sqlite:////tmp/agentfox-scratch.db`. The demo and `seed` write demo
   agents, keys and findings into whatever database they're pointed at.
3. **Nothing leaves the machine by default.** Never pass `--submit`, set
   `AGENTFOX_ALLOW_EGRESS=true` or add provider keys without the user's say-so.
4. **Secrets are shown once.** `auth issue`, credential issue, and `seed --show-keys` print raw
   keys. Don't repeat them, write them to files, or commit them.
5. **Compliance mappings are drafts.** Present framework results with the `DRAFT —
   UNVERIFIED / NOT LEGAL ADVICE` caveat, never as legal conclusions.
6. **Never quote a benchmark number without its limit.** Detection numbers are not robustness
   claims, containment depends on declarations, and compliance mappings are drafts. The standing
   rules are in `docs/evaluation/evidence-standards.md` in the AgentFox repository; the one-line version is
   that we do not claim adversarial robustness and nobody should.
7. **Code wins.** If a doc and the code disagree, trust the code and check
   [reference/known-issues.md](reference/known-issues.md) before assuming a bug is yours.
8. **An automated change is still a change.** Everything the improvement loop wants to do
   is filed as a proposal. Applying or rolling one back is **BLK**, and a change that
   loosens a control is never applied automatically, whatever the evidence says.
   `AGENTFOX_IMPROVEMENT_FROZEN=true` stops automated applies without losing proposals.
9. **Prefer the `agentfox_*` MCP tools for reading and analysis** when they're available;
   they return structured results. Otherwise prefer `--json` where it exists, or the HTTP API
   when a server is running. State changes always go through the CLI.

## Running the CLI

Skills write commands as `agentfox <args>`. If `agentfox` isn't on PATH:

- In a source checkout of the AgentFox repo, use `uv run agentfox <args>`.
- Anywhere, use the launcher `scripts/agentfox.sh <args>` in the runtime plugin's folder
  (`plugins/claude-code/scripts/agentfox.sh` in the repository). With the Claude Code plugin,
  that's `${CLAUDE_PLUGIN_ROOT}/scripts/agentfox.sh`. It finds an
  installed CLI or a checkout, or prints the install line.

Paths such as `src/…` and `docs/…` refer to the AgentFox repository
(https://github.com/architsharm/agentfox). They are local only when you're working inside
a checkout of it.
