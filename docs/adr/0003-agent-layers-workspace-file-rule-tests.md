# ADR 0003: Agent protection layers, the workspace file, and rule tests

**Status:** Accepted, 2026-10-08. Builds on [0002](0002-customer-authored-rules.md).

## Context

Three requests from the competitor comparison: set up one agent in a single guided
flow (as Bedrock does), keep guardrail configuration in git (the NeMo and Guardrails
AI habit), and know before applying a change that a rule still catches what it was
written for. Each needed a home that would not become a second way to decide.

## Decision

1. **An agent's protection is a policy layer.** `capabilities/protection` maps a short
   catalogue of protections (prompt attacks, personal data, …) to shipped rules and
   writes copies, at the chosen threshold and with the agent's end-user message, into a
   pack `agent.<slug>` bound at the *agent* level, composed `extend`. The hierarchy
   already keeps a broader rule in force beside a narrower copy, so an agent can be made
   stricter than the workspace but never weaker. Words and topics are custom rules
   scoped to the agent under keys the flow owns, so re-running it edits rather than
   duplicates.
2. **Generated packs publish through one helper.** `platform/policy/publish.py`
   (`publish_in_current_mode`) saves a version and keeps the pack's mode, simulating
   first when it enforces. The `custom` pack, agent layers and the workspace file all
   use it.
3. **The workspace is one YAML file.** `capabilities/workspace` exports every bound
   policy (mode and placement included), custom rules and detector switches; `plan`
   diffs a file against the workspace; `apply` makes it match. Nothing the file omits
   is removed, enforcing still needs a recorded simulation (and the production role),
   and the apply is one operator-log entry. API, dashboard and CLI share it.
4. **Rule tests are eval cases over recorded decisions.** `platform/policy/examples.py`
   keeps examples in an eval suite `rule:<rule_id>`; each names a decision and whether
   the rule should fire. Checking re-evaluates the stored decision against a candidate
   version (the same replay `simulate` uses), so the Tune preview shows pass/fail
   before Apply.

## Consequences

- Agent setup, tuning, files and imports all end in policy versions; history, rollback
  and audit cover every path.
- `protection.save` and `workspace.apply` are privileged operations
  (`operator_log.PRIVILEGED`).
- A rule test checks the policy, not the detector: changing a custom rule's word list
  is not re-checked by saved tests, because their detections were recorded earlier.
- A workspace file cannot delete; removing a policy or rule stays a deliberate act.

## Alternatives considered

- **Per-agent settings columns on `Agent`.** Simpler to read, but a second place that
  decides, outside versions, simulation and the hierarchy's safety rule.
- **A file that is the source of truth (sync and prune).** What GitOps purists want; one
  bad merge would delete protections. Pruning can be added later behind an explicit flag.
- **Tests that re-run detection on stored text.** Would cover detector changes, but means
  storing raw user text and running models on every preview.
