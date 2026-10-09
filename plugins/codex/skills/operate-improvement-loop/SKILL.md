---
name: operate-improvement-loop
description: Covers the governed improvement loop. It reads the change-proposal inbox, explains what a proposal would change and what proved it, takes a decision under the two-approver rule where that applies, stages a change through a canary, rolls one back, and freezes the loop. Use for "what does it want to change", "review the proposals", "approve this tuning change", "why is this waiting for a second approver", "turn the automation off", or /agentfox:proposals.
---

# Operate the improvement loop

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

The loop never edits configuration directly. Anything it wants to change is filed as a
**proposal** carrying the evidence that prompted it, the proof that it is safe, and a
decision trail. Commands are in
[reference/cli.md](../../reference/cli.md#proposals--governed-changes-improvement-loop),
routes in [reference/http-api.md](../../reference/http-api.md), settings in
[reference/config.md](../../reference/config.md#improvement-loop-and-scheduler), and the
exact rules in `src/agentfox/capabilities/improvement/contract.py`.

One rule sits above the rest: **a change that loosens a control is never applied
automatically.** Direction is computed by the applier from the diff and the live
configuration, not taken from whoever filed it, and recomputed at filing, decision and apply.

## 1. Read the inbox

```bash
agentfox policy proposals list --json
```

Filter with `--status`, `--kind` and `--scope` (org, team, agent, user). Work the list in
this order:

1. `direction: loosens`, because these cannot proceed without a person
2. `awaiting_second_approver: true`, one person has approved an org-level loosening
3. `status: applied` with no `verified_at`, live and nobody has closed it out
4. `status: canary`, live for a cohort and still being gated
5. the rest

## 2. What each status means

| Status | Meaning | Moves to |
|---|---|---|
| `proposed` | filed with evidence, not yet proved | proven, rejected, superseded |
| `proven` | a proof bundle passed, so it can be decided | approved, rejected, superseded |
| `approved` | a person, or an earned autonomy level, said yes | canary, applied, rejected, superseded |
| `canary` | live for a cohort only, health gate running | applied, rolled_back |
| `applied` | live everywhere | verified, rolled_back |
| `verified` | the expected effect was confirmed afterwards | terminal |
| `rejected` | a person said no | terminal |
| `rolled_back` | undone, by a person or by the canary gate | terminal |
| `superseded` | a newer proposal replaced it | terminal |

Any other move is refused as an illegal transition, and a proposal cannot be approved
straight from `proposed`; it has to be proven first.

## 3. Read one proposal before deciding

```bash
agentfox policy proposals show <id> --json
```

Tell the user five things in this order: what it would change (`diff`), which way it moves
the control (`direction`), what prompted it (`evidence`, `related_finding_ids`), what was
proved (`proof`), and how wide it reaches (`scope_level:scope_id`). If `applier` is false,
that kind can only be recommended, never applied.

## 4. Who may act

- **Loosening always needs a person.** No track record changes that. Automation also refuses
  the never-automatic kinds (`control.loosen`, `control.disable`, `grant.widen`,
  `verdict.unblock`, `agent.kill`, `agent.resume`, `compliance.claim`, and the rest).
- **Automation needs four things at once:** an earned autonomy level (L3 or L4), a kind and
  direction the contract allows, the freeze switch off, and headroom under the tenant's daily
  cap. L0 observes, L1 recommends, L2 is one-click for a person, and L3 and L4 apply
  without one. There is no observe stage: an automated tightening is enforced as soon as it
  applies, unless its diff asks for a canary and the kind can be staged (policy kinds only).
- **A class that keeps getting rolled back is demoted** one level, never below L1, while it
  is over the rollback budget (5% by default).
- **Undoing a tightening is a loosening**, so automation may not roll one back either.

## 5. Decide

```bash
agentfox policy proposals approve <id> --actor "you@example.com" --note "why"
agentfox policy proposals reject  <id> --actor "you@example.com" --note "why"
```

Both need a named actor and a note. They go on the audit chain and an auditor reads them.

**The two-approver rule.** A loosening at `org` scope needs two different named people. The
first approval records the approver, and the proposal stays `proven` with
`awaiting_second_approver: true`. A second, different person approving moves it to
`approved`, keeping both notes. The same person approving twice is refused. A loosening below
org scope needs one person, and so does a tightening.

## 6. Apply (BLK: confirm first)

This changes live configuration. Ask the user in this conversation before running it, and let
the plugin's safety-hook prompt.

```bash
agentfox policy proposals apply <id> --actor "you@example.com"
```

Only an `approved` proposal applies. If the diff asks for staging, apply starts a canary
instead of going live and the status becomes `canary`:

- The canary holds for `AGENTFOX_CANARY_MIN_DWELL_SECONDS` (an hour by default) between
  steps, driven by the hourly `canary.advance` job. On a once-a-day cron each step takes at
  least a day.
- The health gate rolls the change back if the candidate blocks much **more** than stable, and
  also if it blocks much **less** (`AGENTFOX_CANARY_MAX_BLOCK_RATE_DROP`). A deliberate
  loosening has to raise that bound when the canary starts.
- Running apply again on a finished canary settles it: completed becomes `applied`, a gated
  rollback becomes `rolled_back`. While it is still rolling, the command refuses and changes
  nothing.

Close the loop with `POST /api/proposals/{id}/verify` `{"verified": …, "note": …}`. A failed
verification rolls the change back, unless that rollback would loosen a control, in which
case the proposal stays `applied` with the failure recorded, for a person to handle.

## 7. Roll back (BLK: confirm first)

```bash
agentfox policy proposals rollback <id> --actor "you@example.com" --reason "what went wrong"
```

Same gate as apply. Write the reason for a future auditor. A rollback restores what the apply
recorded on the chain, and rolls back the canary if one is still running.

## 8. When to run `proposals from-labels`

Run it when people have been labelling detections as false positives and someone wants a
detector to fire less often:

```bash
agentfox policy proposals from-labels --days 30 --json
```

It turns labelled false positives into `policy.rule_min_score` proposals against the rule
that enforces the cut-off and fired on the labelled decisions. Raising a rule's `min_score`
loosens it, so the loop **files proposals and applies nothing**. Each proposal is scoped to
the agents the labels came from (`agent:<slug>`; org-wide only when the labels cover every
agent the rule governs) and carries a replay proof, so it is `proven` and a person can
approve it; one that would lose a labelled true positive stays `proposed`. Show the user
`proof.recorded_detections_that_would_stop_firing`: detections nobody labelled that the
change would also let through. A proposal the labels no longer support is superseded on the
next run. Read the skipped reasons out loud; they usually mean no rule covers that detector.
The same work runs daily as the `tuning.propose` job.

## 9. The kill switch

`AGENTFOX_IMPROVEMENT_FROZEN=true` stops every automated apply. Proposals are still filed and
evidence is still gathered, so nothing is lost while the loop is off. Two limits to state
plainly: it does not stop a person applying a proposal, and it does not pause a canary that
is already rolling, which has to be rolled back explicitly. `AGENTFOX_SCHEDULER_ENABLED=false`
is the wider switch, stopping cron from queuing scheduled work at all. Turning the freeze back
off restores automatic applies, so treat that as the user's decision.

## 10. Hand off

- The rule is wrong, not its threshold: **author-policy** or **business-guardrails**.
- The findings behind the evidence need working through: **triage-findings**.
- A change is live and something is on fire: **incident-response**.
- Scheduled work is not running at all: **operate-deployment**.
