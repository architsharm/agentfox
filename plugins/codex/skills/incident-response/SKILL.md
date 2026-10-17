---
name: incident-response
description: Guides responding to an AI agent misbehaving in production with AgentFox. It establishes what happened from traces and findings, contains the agent with quarantine or kill (confirmation required), maps the blast radius, preserves evidence, and restores service deliberately. Use when an agent is doing something harmful right now, a breach or data leak is suspected, the audit chain fails verification, or for /agentfox:contain.
---

# Incident response

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

Speed matters, but the one thing you must not do is make it worse. Stopping an agent is
itself an outage, so it's the user's call, made with the facts in front of them.

## 1. Establish facts (read-only, about 2 minutes)

```bash
agentfox agents list --json
agentfox findings --json --limit 50
agentfox agents list --stopped
agentfox report verify
```

With a server running, open the recent traces:
`GET /api/traces?agent=<slug>` and `GET /api/traces/{id}`. Also check pending approvals with
`GET /api/approvals?status=pending` (or `agentfox permit approvals list`), because an attack
may be queued waiting for a human to click approve.

Tell the user, in three lines:

- **What happened:** which agent, what action, and when.
- **Whether it is still happening.**
- **What the agent can reach:** see step 3.

## 2. Contain (BLK: confirm first)

Offer the smallest effective option:

| Option | Effect | Command |
|---|---|---|
| Deny a pending approval | stops one queued action | `POST /api/approvals/{id}/deny` or `agentfox permit approvals deny ID` |
| Quarantine | agent stops, reversible, audited | `agentfox agents quarantine <slug> --reason "<incident id / what>"` |
| Kill | stop now | `agentfox agents kill <slug> --reason "…"` |
| Enforce a policy that's in observe | start blocking a class of action for every agent | `agentfox policy enforce <key>` |

The hook will prompt. Write the `--reason` for a future auditor, including the incident id
and who decided. Verify containment with `agentfox agents list --stopped`.

## 3. Blast radius

```bash
agentfox agents lineage <slug> --depth 3
agentfox test action "<the SQL/shell/HTTP the agent ran>" --kind sql
```

Lineage shows tools, data and downstream agents. List what may need checking or rotating:

- the credentials the agent held (`/api/identities`)
- the tables it wrote to
- any messages it sent

## 4. Preserve evidence before anyone "cleans up"

```bash
agentfox admin checkpoint
agentfox report evidence --agent <slug> --since-days 7 --requested-by "incident <id>"
```

If `audit verify` failed in step 1, **don't checkpoint**. Export the evidence and record the
first broken entry; the break is itself evidence. See `docs/architecture/threat-model.md` §E.2.

## 5. Fix, then restore deliberately

- **Root cause:** decide whether it was policy (**author-policy**), integration (untrusted
  content not marked; **integrate-guardrails**), or a missing control
  (**declare-agent-controls**).
- **Prove the fix:** replay with `agentfox policy simulate -f <fixed policy>`, and/or re-run the
  red-team probe that reproduces it.
- **Resume only on the user's go-ahead** (BLK):
  `agentfox agents resume <slug> --reason "fixed by <change>"`.

## 6. Write it up

Write a short timeline covering detection, containment, blast radius, root cause, fix,
evidence package path and follow-ups. The audit log has the exact timestamps of every step
you took.
