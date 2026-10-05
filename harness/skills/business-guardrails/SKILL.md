---
name: business-guardrails
description: Turns a written business rule or policy document ("refunds over $500 need a manager", a spend limit, a tenant-isolation rule) into an executable AgentFox business guardrail in observe mode, tests it with concrete values, and checks it for conflicts with other teams' rules. Use when a non-engineer's rule needs to become enforcement, or for /agentfox:guardrail.
---

# Business guardrails

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

This is the no-code path. The user describes the rule in words, and the product has 22
guardrail kinds to express it. Your job is to pick the kind, fill in the parameters,
prove the rule does what the user said, and leave it in observe mode.

## 1. Understand the rule

Restate the rule back to the user as bands or conditions before building anything.
"Refunds up to $100 go through, $100–$500 need a risk check, anything above needs finance
approval." Ambiguity about boundaries is the most common bug, so ask whether $500 exactly
is in or out.

## 2. Pick the kind

```bash
agentfox policy rules suggest "<the rule, verbatim>"
agentfox policy catalogue
agentfox policy rules explain <kind_id>
```

`explain` prints the parameters and a worked example. For a longer policy document, run
`guardrails compile FILE --json` to see how each sentence maps. Sentences reported as
"not expressible as a guardrail" need a policy rule (**author-policy**) or a human process.
`compile FILE --apply` saves the threshold ladders it found in observe mode. Other rule kinds
still need a YAML file and `guardrails apply`.

## 3. Write the rule file

Start from [templates/threshold-ladder.yaml](templates/threshold-ladder.yaml), which is
verified against `guardrails explain threshold_ladder`. Keep it next to the user's code,
for example `governance/guardrails/refund-approval.yaml`, so it's reviewed like code.

- `tool` must match the tool key the agent actually calls (see `agents lineage <slug>`).
- `field` must be a dotted path that exists in that tool's arguments. Otherwise the rule is
  "configured but inert".
- Bands are ordered. Each has `upto` (inclusive) and an `outcome`, and the last band omits
  `upto`.

## 4. Apply in observe, then prove it

```bash
agentfox policy rules apply governance/guardrails/refund-approval.yaml --mode observe
agentfox policy rules show refund-approval
agentfox test rule refund-approval "0,10,10.01,100,500,500.01,100000"
agentfox policy rules check
```

- Test the **boundaries** the user named, plus one value on either side of each.
- Show the user the `test` output as a table and have them confirm every row.
- `guardrails check` exits 1 when two teams' rules disagree. Surface each conflict with both
  owners. Don't pick a winner yourself.
- `guardrails graph` shows where the rule sits in the decision path, which helps when
  explaining it to a non-engineer.

## 5. Promotion is the user's call

Moving to `--mode enforce` blocks or escalates real actions, and the hook will ask. Before
proposing it, check two things:

1. The observe period produced decisions (`findings`, or the dashboard's `/guardrails`
   page), and none surprised the user.
2. The approver role in an `escalate` band has a human who will actually see approvals
   (`/approvals` in the dashboard).
