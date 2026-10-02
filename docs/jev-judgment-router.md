# Routing policy predicates between code and a judgment model

Measured against TypeSafe's Jev 1.13 over roughly 150 calls, on a refund-agent
guardrail. Everything here is from running it, not from the vendor's claims.

## Capacity

One request carries many questions and latency barely moves.

| questions | latency | correct | input tokens |
|---|---|---|---|
| 8 | 416 ms | 8/8 | 440 |
| 32 | 296 ms | 32/32 | 863 |
| 128 | 356 ms | 128/128 | 2,555 |
| **512** | **524 ms** | **512/512** | **9,323** |

At $0.042 per million input tokens with output free, that 512-question call costs
about four millionths of a dollar. A tenant with hundreds of policies can have all
of them judged in one round trip, so the design should ask *more* narrow questions,
not fewer.

## The one failure mode

| What Jev matched | What it ignored | Cases |
|---|---|---|
| amount within limit | elapsed days | 89 and 30 days against a 90-day window |
| user_id | account_id | cross-tenant request scored 0.78 "entitled" |
| role = support agent | acting_for_user_id | delegation check scored 0.53 |
| merchant and amount | descriptor | "monthly plan", "instalment 1 of 3" |

**Jev weights the salient, typical signal and under-weights a qualifying field that
contradicts it.** One mechanism, showing up in numbers, identifiers and free text.

Two properties make it dangerous rather than merely imperfect. The wrong answers are
*confident and reproducible* — 0.98 on eight consecutive runs — so no confidence
threshold catches them. And **JSON key order alone** moved the same question over the
same values from a median 0.53 to 0.98.

Meaning questions are unaffected: spread 0.00–0.01 across the same perturbation,
against 0.45 for a predicate question.

## Three representations of one policy, measured

| | correct | false ALLOW | false block |
|---|---|---|---|
| R1 full policy text, one judgment | 21/24 | 3 | 0 |
| R2 decomposed into prose sub-questions | **19/24** | **5** | 0 |
| R3 routed — code for comparisons, Jev for meaning | 22/24 | 1 | 1 |
| **R4 union — block if any representation blocks** | **23/24** | **0** | 1 |

Two things to take from this.

**Decomposition alone makes it worse.** R2 scores below R1. Splitting a policy into
more prose questions just creates more comparisons for the model to get wrong.
Decomposition only helps when each piece is then routed to whoever can evaluate it.

**The model-only representations fail in one direction.** R1 and R2 produced eight
errors between them and every single one was a false allow. Zero false blocks. For a
guardrail that is the worst possible bias: each error is a breach, none is an
inconvenience. R3's single false block came from a threshold this code chose, not
from the model.

The union is the safest configuration available here: zero false allows, at the cost
of one over-block that is threshold-tunable.

## What this package does

`Comparison` and `Identity` carry operands and an operator and are always evaluated
in Python. `Semantic` has no such fields, so a comparison cannot be expressed as a
judgment — and `lint_semantic` rejects one smuggled in as prose, which is the bug
that started this work:

```python
Semantic(
    id="no_recent_refund",
    instructions="Has the account had a refund within the last 90 days?",
    ...
)
# PredicateMisrouted: semantic question contains 'within the last', which is a
# comparison. Jev is not a calculator and this is the shape that fails confidently
# rather than uncertainly.
```

Invariants, each bought by a measured failure:

- **Unevaluable is a verdict.** 45 GBP against a 50 USD limit has no answer without a
  rate. Jev scored every GBP amount 0.58–0.64 regardless of size. Code returns
  `UNKNOWN` and the composer escalates.
- **A judgment may raise severity, never clear it.** Every measured error was an
  under-flag, so authorisation starts closed and only a code predicate discharges it.
- **One signal per question.** `Semantic.weighs` is required. The bundled duplicate
  question weighed merchant, amount, timing and descriptor at once and scored 0.64;
  the descriptor alone scored 0.96.
- **`sort_keys=True` on every payload**, because key order moved an answer by 0.45.
- **Identity never goes to a model.** Tenant isolation is one of the four controls
  that may not fail open.

## Not settled

- 24 hand-written cases is not calibration. These thresholds need fitting against the
  containment suite before anything ships.
- Latency measured from here is ~330 ms; a third party reports 151 ms median from
  their own serving. The difference is likely the network leg, so the question of
  whether this fits a 300 ms synchronous budget has to be re-measured from the
  deployment region.
- Egress: there is no self-hosted Jev, and `allow_egress` defaults to false.
- A question and its negation do not sum to 1 (a published example gives 1.19), so a
  Noul is not a probability you can do arithmetic on. Weighted-sum composition needs
  weights fitted on our own data.
