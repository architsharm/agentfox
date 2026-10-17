---
name: declare-agent-controls
description: Declares the agent-specific controls that stop the business failures content filters miss. Covers what an agent may answer from (abstention), which sources are authoritative, who the agent acts for and what they may see, when a human must take over, and which tables are row-scoped. Use when an agent gives confident wrong answers, cites stale docs, over-shares data, misses handoffs, or runs queries across tenants.
---

# Declare agent controls

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

Each control maps to a failure family in `docs/design/failure-modes.md`. Ask which failure the
user is worried about, then do only that section. Every command here is in
[reference/cli.md](../../reference/cli.md#agent-controls--boundary-sources-escalation-entitlement-p7-p8-p10-p11).
Everything starts in `observe`.

Precondition: the agent is registered. Run `agentfox agents list` and check it's there. If it
isn't, go through **onboard-codebase** first.

## F1 — answering without the data (knowledge boundary)

```bash
agentfox declare boundary <agent> --systems "zendesk,billing-db" \
  --coverage-months 24 --answerable "fact,aggregate,procedure" --out-of-scope "legal advice,medical" --mode observe
agentfox test boundary <agent> "What was our refund rate in 2019?"
```

Try three questions with the user: one clearly in scope, one out of the coverage window,
and one out of scope. Show what the agent would say instead of answering.

## F2 — trusting the wrong source (source authority)

```bash
agentfox declare source policies/refunds.md --tier system_of_record --owner support-ops --sla-hours 720 --updated now
agentfox declare list sources --json
```

The tiers are `system_of_record` > `approved` > `unverified` > `external`. For many sources,
write a JSON list and run `sources import FILE`. Stale sources past their SLA show up at the
top of `sources list`.

## F4 — over-sharing (entitlement and purpose)

```bash
agentfox declare principal alice@corp.com --groups "support,emea" --clearances "internal"
agentfox permit user "crm/accounts/*" support --kind group --classes "internal" --purposes "support"
agentfox report entitlement --days 7
```

The report shows how much more the agent can reach than its callers are entitled to. That
gap is the over-sharing risk. The agent must pass the end user through, using
`agentfox_principal=` on `auto()`-patched calls or `principal` on the gateway body.
Otherwise there is nothing to check against.

## F5 — missed human handoffs (escalation)

```bash
agentfox declare escalation --agent <agent> --turn-depth 8 --repeated-failure 2 --sla-minutes 30 --owner support-leads --mode observe
agentfox report escalations --hours 72
```

Run the scan first, before `set`, so the user sees how many conversations already qualified
and never reached a human. Only add `--apply` when they want findings raised for those.

## F3 — cross-tenant or unbounded data access

```bash
agentfox declare scope orders --column customer_id --restricted-columns "card_last4,email"
agentfox declare reference countries
agentfox declare triggers db.orders.update --triggers "webhook:fulfilment,trigger:audit_log"
agentfox test action "UPDATE orders SET status='void'" --kind sql
```

An undeclared table is reported, never silently assumed safe. Declare the ones the agent
touches (see `agents lineage <agent>`).

## Close

Summarise what's now declared and still in observe. Tell the user where to watch:
`agentfox findings`, or the dashboard's `/escalation`, `/entitlement` and `/sources` pages.
Switching any of these to `--mode enforce` is a BLK step, and the hook will ask.
