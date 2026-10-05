---
name: eval-gate
description: Sets up AgentFox's evaluation regression gate. It runs a suite, pins a baseline, and fails CI when quality regresses, and it adds a governance CI workflow that also fails on ungoverned model calls, conflicting guardrails, risky policy lint findings and a broken audit chain. Use for "block regressions in CI", "add an eval gate", drift monitoring, or /agentfox:gate.
---

# Eval gate

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

## 1. Know what suites exist

The CLI can run and gate suites but not create them. Suites and cases come from `seed`
(the `support-quality` demo suite), the HTTP API, or the dashboard's `/evals` page:

```bash
curl -s -X POST "$NOMETRIA_API_URL/api/eval/suites" -H "Authorization: Bearer $NOMETRIA_API_TOKEN" \
  -H 'content-type: application/json' -d '{"key":"refund-answers","name":"Refund answers","tags":["support"]}'
curl -s -X POST "$NOMETRIA_API_URL/api/eval/suites/refund-answers/cases" -H "Authorization: Bearer $NOMETRIA_API_TOKEN" \
  -H 'content-type: application/json' -d '{"input":"Can I get a refund after 45 days?","expected":"No — 30 day window","context":["policies/refunds.md"]}'
```

The best cases come from real traffic:
`POST /api/eval/suites/{key}/cases/from-trace?trace_id=…` turns a production trace into a
regression case.

## 2. Run and pin a baseline

```bash
agentfox test run <suite>
agentfox test baseline <run_id> --label main
```

The default provider is the offline `echo` model, which is fine for proving the plumbing. To
evaluate the real model, the user sets `NOMETRIA_ALLOW_EGRESS=true` plus the provider key,
and you pass `--provider openai --model <model>`. Ask before enabling egress.

## 3. Gate

```bash
agentfox test gate <suite> --baseline <run_id> --junit reports/eval.xml --sarif reports/eval.sarif
```

- Exit 1 means a regression against the baseline, or a pass rate below `--min-pass-rate`.
- Explain which cases flipped, and which scorer flagged them (for example groundedness or
  silent-failure scorers).

## 4. Add the CI workflow

Copy [templates/agentfox-governance.yml](templates/agentfox-governance.yml) to
`.github/workflows/`. Adapt the install line to the user's project, and the suite and
baseline to theirs. Each step fails the build for a different reason:

| Step | Fails when |
|---|---|
| `agentfox scan . --fail` | a new model call is not governed |
| `agentfox policy lint` | the policy hierarchy has critical/high findings |
| `agentfox policy rules check` | two teams' business rules conflict |
| `agentfox test gate` | quality regressed against the baseline |

## 5. Production drift (after launch)

```bash
agentfox test online <agent> --since-days 7 --rate 0.1
agentfox report drift <agent> --scorer groundedness
```

`eval drift` exits 0 even when drift is detected, so read its output. SLOs live at
`POST /api/eval/slos`.
