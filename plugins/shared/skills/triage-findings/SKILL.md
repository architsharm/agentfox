---
name: triage-findings
description: Turns AgentFox's open findings into a prioritised, grouped action list with a recommended move for each, and applies suppress/resolve decisions only with the user's agreement. Use when the user asks "what did it find", "what should I fix", "go through the findings", or runs /agentfox:findings.
---

# Triage findings

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

## 1. Pull the queue

```bash
agentfox findings --json --limit 200
```

To filter, add `--severity critical` (or high, medium, low). An empty list on a new install
usually means nothing has been governed yet; `agentfox doctor` confirms it.

## 2. Group before you judge

Group by `type`, then by `subject_id` (the agent, server or tool). Twenty
`guardrail_detection` findings on one agent are one problem, not twenty. The same
underlying problem recurring is already one row with an `occurrences` count rather than a
new finding each time, so read that count before calling something rare. The
`agentfox_finding_occurrences` MCP tool ranks findings by it; the `findings` CLI does not
show it. Order the groups by:

1. **critical/high on a production agent**
2. **anything that means "something ran that nobody owns"**: `shadow_agent`,
   `unowned_agent`, `undeclared_mcp_tool`, `mcp_schema_drift`
3. **quality regressions**: `regression`, `drift`, `redteam`
4. the rest

## 3. Decide per group

Use the "first move" column in
[reference/detectors-and-findings.md](../../reference/detectors-and-findings.md#findings-the-queue-agentfox-findings-reads).
For detections, look at the evidence before calling anything a false positive:

- `evidence_json` holds the entities, rules fired, and the trace id.
- If a server is running, `GET /api/traces/{trace_id}` shows the full request path.
- The dashboard shows the same at `/traces/<id>`.

A detection in `retrieved` or `tool_result` content is almost always worth keeping. That is
the indirect-injection path.

## 4. Present the triage

Give one table, one row per group:

| Group | Count | Severity | What it means | Recommended action |
|---|---|---|---|---|

Follow it with a single recommended next action. Don't list every possible fix.

## 5. Apply decisions only when the user agrees

Finding status changes are audited, and an auditor will read the reasons, so write them for
that reader.

```bash
curl -s -X PATCH "$NOMETRIA_API_URL/api/findings/<id>" \
  -H "Authorization: Bearer $NOMETRIA_API_TOKEN" -H 'content-type: application/json' \
  -d '{"status":"suppressed","suppression_reason":"<why this is expected, who decided>"}'
```

- `resolved` requires a `note`.
- `suppressed` requires a `suppression_reason`.
- For false positives, prefer `POST /api/guardrails/feedback` so detector precision improves,
  over suppressing one finding at a time.
- Without a running server, open the dashboard's `/findings` page instead (see
  **operate-deployment**).

## 6. Hand off

Hand off to the skill that owns the fix:

- Policy too loose or too tight → **author-policy**.
- A business rule is missing → **business-guardrails**.
- Answerability, sources, escalation or entitlement → **declare-agent-controls**.
- Shadow agents → **onboard-codebase** for that service.
- An active incident → **incident-response**.
- Enough labelled false positives that a detector's cut-off should move →
  **operate-improvement-loop** (`proposals from-labels` files it; raising a cut-off
  loosens a rule, so a person decides it).
