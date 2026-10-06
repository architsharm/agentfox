---
title: Detectors, verdicts and findings
layer: reference
audience: agents triaging results
source_of_truth: src/agentfox/detection/, src/agentfox/runtime/enforcement/, src/agentfox/core/models/ (Finding), src/agentfox/platform/ledger/findings.py
verified_against: branch claude/improvement-loop-phase0, 2026-09-20
---

# Detectors, verdicts, findings

## Surfaces

Content is checked per **surface**: `input`, `output`, `retrieved`, `tool_result`,
`tool_args`, `memory_write`, `agent_message`. Content from `retrieved`, `tool_result` and
sub-agent output is **tainted**. Taint follows it into tool arguments, which is how an
indirect injection is contained even when no detector fires.

## Detectors

| Key | Detects | Needs |
|---|---|---|
| `injection.heuristic` | Lexical/structural injection, jailbreak, role override, hidden chars, encoded payloads, exfiltration; also reads letter-spaced words and text hidden in HTML comments, hidden elements and markdown link titles (`INJECTION.*`, incl. `HIDDEN_INSTRUCTION`) | built in, on by default |
| `pii.native` | Regex PII packs: email, phones, SSN, cards, IBAN, NHS, Aadhaar, PAN, IP, DOB, … (`PII.*`) | built in, on |
| `secrets.native` | API keys, tokens, JWTs, private keys, connection strings (`SECRET.*`) | built in, on |
| `safety.lexicon` | harm, harassment, self-harm, illicit, extremism, sexual (`SAFETY.*`) | built in, on |
| `schema.json` | output / tool-arg JSON Schema violations (`SCHEMA.*`) | built in, on |
| `CRESCENDO.TRAJECTORY_DRIFT` | gradual multi-turn escalation, scored on the *slope* across a rolling window rather than any single turn (`trajectory.py`) | built in, runs where a session id is supplied |
| `pii.presidio` | Presidio NER PII (adds PERSON, LOCATION, DATE_TIME) | `[pii]` |
| `injection.classifier` | PIGuard + deberta ensemble — the benchmarked injection detector | `[classifiers]` |
| `injection.similarity` | embedding similarity to a known-attack corpus | `[classifiers]` |
| `safety.granite` | IBM Granite Guardian | `[classifiers]` + weights |
| `safety.restricted` | Llama Guard (non-OSI licence) | `[restricted-classifiers]` + explicit licence env var |
| `rails.nemo`, `rails.guardrails_ai` | NeMo Guardrails / Guardrails AI validators | `[rails]` / `[validators]` |

`agentfox doctor` lists which detectors are actually available. Enable extras with
`AGENTFOX_ENABLED_DETECTORS` (JSON list).

Non-detector analysis also feeds policy: action assurance on SQL/shell/HTTP (`[sql]`, fails
closed without it), taint tracking, composed privilege escalation, loop and budget governance.

## Verdicts (weakest → strongest)

`allow` → `tokenize` → `mask` → `redact` → `abstain` → `escalate` → `block`

- **`verdict`** is what was enforced. **`effective_verdict`** is what the policy would have
  done. In observe mode they differ: `verdict=allow`, `effective_verdict=block` means
  "would have blocked". This is the number to read before promoting to enforce.
- `escalate` creates an **approval** (`GET /api/approvals?status=pending`). The call waits
  for a human.
- `degraded` lists detectors that timed out or errored. Under `fail_mode: open` the call went
  through anyway.

## Findings (the queue `agentfox findings` reads)

Persisted in `models.Finding`: `id, type, severity (critical|high|medium|low), status
(open|suppressed|resolved), title, subject_type, subject_id, evidence_json, control_keys,
fingerprint, occurrences, last_seen_at`.

**One row per problem, not per detection.** A finding is identified by a `fingerprint` over
its type, subject and identifying parts. The same problem happening again increments
`occurrences` on the open or suppressed finding, refreshes the evidence (keeping the
first-seen evidence) and `last_seen_at`, and ratchets severity up; it never adds a row. A
milder recurrence never downgrades a finding someone is triaging. A problem that recurs
after being resolved reopens the same finding, keeps what the previous resolution said, and
writes a `finding.recurred` entry to the audit chain, so `occurrences` counts the whole
history. Findings raised before fingerprints existed have none, and count 1.

`agentfox findings --json` does not include the count. `GET /api/findings`, `GET
/api/findings/{id}` and the `agentfox_finding_occurrences` MCP tool do.

| Type | Meaning | First move |
|---|---|---|
| `shadow_agent` | model traffic from an unregistered agent | find the owner; register it, or kill it |
| `unowned_agent` | registered, no owner | assign an owner (`PATCH /api/agents/{slug}`) |
| `registry_drift` | runtime behaviour ≠ declared tools/models | update the registration, or investigate |
| `undeclared_mcp_tool`, `mcp_schema_drift` | MCP server changed under you | re-scan with `scan mcp SERVER --file tools.json`; treat drift as suspicious |
| `guardrail_detection` | a detector rule changed (or, in observe, would have changed) the outcome. Titled from the detector rules alone — a PII rule that merely fired alongside a capability refusal is no longer reported as the cause | open the trace; true positive → keep, false positive → feedback/suppression |
| `containment` | a tool call was stopped or held by a non-detector rule: no grant, outside a grant's limits, untrusted provenance (taint), composition, blast radius, destructive SQL/shell, undeclared tool. One per (agent, tool, rule); the title is the story, e.g. `support-bot tried to send_email with data that came from a web page (contained)`; `would have been …` when the rule is in observe. `evidence_json.cause` names the cause | contained → confirm it was an attack or fix the grant; would-have-been → decide whether to promote the policy |
| `regression`, `drift`, `over_refusal` | eval quality moved | compare with the baseline run |
| `redteam`, `redteam_over_block` | a probe got through, or a benign probe was blocked | tighten policy, or loosen an over-broad rule |
| `missed_escalation`, `incomplete_handoff`, `handoff_sla_breach` | a human should have been involved | `escalation scan`; fix the escalation policy |
| `boundary_breach` | answered outside its knowledge boundary | `boundary set` / `boundary check` |
| `control_flow` | a tool call whose *existence* traces to untrusted content, not to the user's instruction — arguments may be perfectly clean | treat as an injected step; check what the agent read just before it |
| `sycophancy` | the answer adopted a false premise the user asserted instead of correcting it | check the grounded record; the answer is wrong in a way groundedness scoring cannot see |
| `agent_loop_stopped` | the proxy stopped a runaway tool-calling loop | look for a repeating call with no progress; check the loop budgets |
| `redteam_mutation_class` | an adaptive campaign got a known attack class through by mutation | read which mutation class worked; it names the weak spot |
| `redteam_posture_regression` | this deployment got weaker than the last comparable campaign | diff the grants, impacts and policy modes since then |
| `budget_breach`, `budget_exhausted` | cost/loop limits hit | check for runaway loops |
| `delegation_depth`, `delegation_cycle` | agent-to-agent delegation got too deep or looped | inspect lineage |
| `agent_stopped` | kill switch or quarantine used | confirm it's intended; `agents resume` when cleared |

Close a finding with `PATCH /api/findings/{id}`: `suppressed` needs a reason, `resolved`
needs a note. Both are audited, so write reasons a human auditor can read.
