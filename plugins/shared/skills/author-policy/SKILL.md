---
name: author-policy
description: Guides writing or changing an AgentFox policy safely. It drafts YAML, validates and lints it, simulates it against recorded production decisions to see exactly what would newly block, saves it, and promotes to enforce only on the user's explicit approval (optionally via canary). Use for "block X", "allow Y", "why was this blocked", "make the policy stricter", or /agentfox:policy.
---

# Author a policy

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

Policies are declarative YAML compiled to Rego, and they are versioned and audited. The
schema is in [reference/policy-schema.md](../../reference/policy-schema.md). The three shipped
packs in `src/agentfox/policies_data/` are the best examples: `baseline`,
`tool-containment` and `eu-ai-act-high-risk`.

**For a business threshold** (amount bands, approvals by value, spend budgets), use the
**business-guardrails** skill instead. It's safer and has boundary tests built in.

## 1. See what's in force now

```bash
agentfox policy list
agentfox policy effective --agent <slug> --environment production
```

`effective` shows which rule wins and where it came from: org, team, agent or user level.
If the user asked "why was this blocked", the answer is usually here plus the trace's
`rules_fired`. Explain before changing anything.

## 2. Draft

Copy [templates/candidate-policy.yaml](templates/candidate-policy.yaml) to the user's repo,
for example `governance/policies/<key>.yaml`, and edit it. Keep these rules:

- `mode: observe`, always, in a draft.
- One behaviour per rule, with a `reason` a user will see and an auditor will read.
- The narrowest `when` that captures the intent: scope by `surface`, `tool`, `agent` first.
- `effect` is the weakest one that solves the problem. The order is allow < tokenize < mask <
  redact < abstain < escalate < block. `escalate` usually beats `block` for business
  actions.
- Map to controls (`NOM-…`) where one applies, so the evidence package can cite the rule.

## 3. Validate and lint (offline)

```bash
agentfox policy validate governance/policies/<key>.yaml
agentfox policy lint
```

`validate` exits 1 on schema errors and prints the compiled rule count. `lint` exits 1 on
critical/high findings across the whole hierarchy, such as shadowed or conflicting rules.

## 4. Simulate against real traffic

```bash
agentfox policy simulate -f governance/policies/<key>.yaml --since-days 30
```

It replays up to 1,000 recorded decisions. **Exit 1 means the candidate would newly block
production traffic.** That isn't an error; it's the diff you show the user. Present it in
three parts:

- **Newly blocked or escalated:** count, plus 3–5 real examples.
- **Newly allowed:** watch for these; loosening is how incidents happen.
- **Unchanged:** count.

If there's little recorded traffic, say that the simulation can't prove much, and suggest
observing longer.

## 5. Save a new version

Pick one path:

- **Control plane running (preferred):** `POST /api/policies` with
  `{"body": "<yaml text>", "notes": "<why>", "mode": "observe"}`. It's versioned and audited,
  and the dashboard's `/policies` page does the same.
- **Local or offline:** put the file in a directory, point `NOMETRIA_POLICIES_DIR` at it, and
  run `agentfox init`. This loads every `*.yaml` in that directory, alongside the policies
  already in the database. It doesn't remove the shipped packs.

Check it landed with `policy list`.

## 6. Promote (BLK: only on explicit approval)

Offer the options, and wait for the user to pick:

| Option | When |
|---|---|
| Stay in observe and watch `effective_verdict` for a week | default for anything customer-facing |
| Canary: `POST /api/policies/{key}/canary/start`, then `…/advance` or `…/rollback` | a server is running and traffic is meaningful |
| `agentfox policy enforce <key>` | the user has seen the simulation and says "enforce it" |

In-process `agentfox.auto()` users also need `auto(mode="enforce")` to raise. Tell them.

To roll back, run `agentfox policy observe <key>`. It's immediate and audited.
