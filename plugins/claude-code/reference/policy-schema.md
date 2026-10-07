---
title: Policy YAML schema
layer: reference
audience: agents authoring or explaining policy
source_of_truth: src/agentfox/platform/policy/model.py (PolicyDocument, Rule, Condition), platform/policy/engine.py
verified_against: commit 6863b8b, 2026-09-15 — template validated with `agentfox policy validate`
---

# Policy schema

Policies are YAML. They compile to Rego (`GET /api/policies/{key}/rego`), and the native
engine evaluates them by default (`NOMETRIA_POLICY_ENGINE=opa` switches to OPA). Examples:
`src/agentfox/packs/*/policies/` and
`plugins/shared/skills/author-policy/templates/candidate-policy.yaml`.

## Document

| Field | Type / values | Default |
|---|---|---|
| `key` | unique id | required |
| `name`, `description` | text | `""` |
| `version` | int | 1 |
| `mode` | `observe` \| `enforce` | `observe` |
| `default_effect` | an effect | `allow` |
| `fail_mode` | `open` \| `closed` — what a detector error or timeout does. `closed` blocks a degraded call when the pack is enforcing and has a detection rule on that surface; the deployment-wide `fail_mode` also applies (stricter wins) | `open` |
| `scope` | e.g. `{agents: ["support-*"], environments: ["production"]}` | `{}` |
| `rules` | list of rules | `[]` |

## Rule

| Field | Notes | Default |
|---|---|---|
| `id` | unique within the policy, dotted by family (`refunds.cap`) | required |
| `description` | for authors | `""` |
| `when` | a condition; **every field present must match** | matches everything |
| `effect` | see precedence below | `block` |
| `reason` | shown to the caller and written to the audit log — write it for a human | `""` |
| `controls` | `NOM-…` control ids this rule evidences | `[]` |
| `severity` | `critical` \| `high` \| `medium` \| `low` | `medium` |
| `enabled` | bool | `true` |
| `redaction` | redaction style when the effect redacts | `mask` |
| `overridable` | can a lower level (team/agent/user) override it | `false` |

## Effects and precedence

When several rules fire, the strongest wins:

`allow (0) < tokenize (1) < mask (2) < redact (3) < abstain (4) < escalate (5) < block (6)`

`escalate` creates a human approval. `abstain` withholds an answer without treating the
user as an adversary.

## Condition (`when`)

| Field | Matches |
|---|---|
| `surface` | list of `input`, `output`, `retrieved`, `tool_result`, `tool_args`, `memory_write`, `agent_message` |
| `environment` | list, e.g. `[production]` |
| `agent` | glob on the agent slug |
| `risk_tier` | list, e.g. `[high]` |
| `tool` | glob on the tool key, e.g. `payments.*` |
| `tool_impact` | list of `read`, `write`, `high_impact`, `irreversible` |
| `detection` | `{entity: PII.CREDIT_CARD}` or `{entity_prefix: INJECTION}`, plus `min_score` (0.5) and `min_count` (1) |
| `argument` | `{path, op, value}`; `op` is one of `eq ne gt gte lt lte in not_in contains matches` |
| `taint_exceeds` | an argument's taint is above this level. Order: `none < user < retrieved < tool_result < subagent < memory` |
| `capability` | `denied` \| `requires_approval` \| `granted` (from the identity's grants) |
| `action_operation` | list of `read`, `write`, `destructive`, `admin`, `unknown` (SQL/shell/HTTP analysis) |
| `blast_radius_at_least` | `none < bounded < unknown < unbounded < catastrophic` |
| `action_reversible` | bool |
| `action_risk` | glob on a risk code, e.g. `sql.*`, `shell.destructive` |
| `budget_exceeded`, `loop_detected`, `intent_declared`, `detector_degraded` | bool runtime state |
| `expr` | escape hatch; avoid it, because it's hard to lint and to explain |

Detection entity names are listed in `reference/detectors-and-findings.md`. For the full
list for your install, see `GET /api/detectors`.

## Hierarchy

Policies compose across levels (org → team → agent → user) with `compose: extend`, set when
saving through the API. `agentfox policy effective --agent X` shows the resolved result and
where each rule came from. `agentfox policy lint` finds shadowed and conflicting rules.

## Lifecycle

`validate` (offline) → `lint` → `simulate` (replay recorded decisions) → save (API or
`NOMETRIA_POLICIES_DIR` + `init`) → observe → canary or `policy enforce` → `policy observe`
to roll back. The procedure is in `plugins/shared/skills/author-policy/SKILL.md`.
