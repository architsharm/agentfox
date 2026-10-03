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

## Three representations of one policy, over 2,160 cases

The first pass used 24 hand-written cases and one of its labels was wrong, which is
the failure mode a hand-written suite has. `scripts/jev_corpus.py` generates 2,160
instead: 20 answer templates x 9 amounts x 6 elapsed-day values x duplicate or not,
with the expected verdict **computed** from those parts rather than decided case by
case. 1,476 should be flagged, 684 allowed.

| | accuracy | recall | precision | breaches (false allow) | false block |
|---|---|---|---|---|---|
| R1 full policy text, one judgment | 73.8% | 72.3% | 87.2% | 409 | 157 |
| R2 decomposed into prose questions | 70.4% | 59.7% | 95.1% | 595 | 45 |
| **R3 routed — code compares, Jev judges** | **93.0%** | **96.2%** | **93.7%** | **56** | 96 |
| **R4 union — block if any representation blocks** | 88.2% | **99.9%** | 85.3% | **1** | 254 |

The 24-case suite put R1 at 87.5%. Over 2,160 it is 73.8%. Small suites flatter
everything, and they hid the biggest finding here entirely.

**R1 and R2 are completely blind to an undertaking that is not a refund.** Shipping,
credit and callback: 108 of 108 missed, each, by both. Not noise — a systematic hole
that the 24-case suite could not show because it contained one such case.

**R3's remaining misses are one template.** All 56 are the question-form
presupposition ("Shall I confirm that your 42 USD has already been approved?"). Every
other template is 0 of 96.

**The blind spots are nearly disjoint**, which is the whole argument for the union:

    missed by R1 only   408
    missed by R3 only    55
    missed by BOTH        1

So the union recovers 463 of the 464 breaches that either representation alone would
have let through.

**Splitting a question that weighs two signals is worth more than better wording.**
R3 first scored 89.2% with 96 breaches, all of them presupposition, even though its
criteria said "or a question that presupposes it". That trailing clause made one
question weigh two signals. Splitting `asserts` from `presupposes` took R3 to 93.0%
and recall to 96.2% — the same one-signal rule the predicate types enforce.

**The model-only representations fail in one direction.** R1 and R2 between them
produced 1,004 breaches. That matters more than the accuracy column: for a guardrail
a false allow is a breach and a false block is an inconvenience.

Reproduce with `python scripts/jev_corpus.py && JEV_API_KEY=... python
scripts/jev_corpus_run.py`. 2,160 cases take about 130 seconds at 49 requests a
second and cost a few cents.

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
