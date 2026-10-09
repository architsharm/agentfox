---
name: using-agentfox
description: Entry point for any work involving AgentFox, the AI-agent governance control plane (guardrails, policy, findings, audit, compliance, red-team, the `agentfox` CLI or `agentfox.auto()`). Load it first. It holds the golden safety rules and routes to the right task skill.
---

# Using AgentFox

Read [AGENTS.md](../../AGENTS.md) at the root of this plugin **now**. It holds the golden
rules (observe before enforce, scratch databases, no egress, secrets shown once, draft
compliance mappings) and the table that routes the request to one task skill. Then load
that skill.

This skill exists because plugin runtimes load skills, not root-level context files.
AGENTS.md stays the single home for the rules, so any agent runtime reads the same text.
