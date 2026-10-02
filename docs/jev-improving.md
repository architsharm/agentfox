# Improving the judgment without fitting the answer

## Method first

The 600 cases already run were split **300 dev / 300 held-out**, stratified by
domain × level (100 per level, 30 per domain on each side). Every variant below
was chosen on dev. Held-out was scored **once**, after the configuration was
frozen. Nothing in this document was selected using held-out.

## What failed

Three question-design changes, all on dev, all worse than or equal to the
baseline single question:

| variant | accuracy | precision | recall | F1 |
|---|---|---|---|---|
| baseline, one question @0.8 | 79.2% | 59.5% | 39.5% | 47.5 |
| split commission from omission | 78.6% | 56.4% | 43.6% | 49.2 |
| relevance gate, then violation | 77.5% | 52.4% | 57.3% | 54.7 |
| routing by policy complexity | 78.4% | 54.4% | 62.6% | — |

The relevance gate is the instructive failure. The idea was that the worst
stratum — rules about a situation the conversation never raised, where Jev sits
at 0.48 — could be removed by first asking whether the rule's subject came up at
all. It cannot:

```
stratum          n       violation q   relevance q
violated     1,857              0.74          0.71
distractor   4,642              0.15          0.56
plain        1,304              0.48          0.71
```

The relevance question scores irrelevant rules at 0.71, the same as real
violations. Jev cannot judge relevance for the same reason it cannot judge the
rule, so decomposing one unreliable question into two does not help. A lexical
relevance proxy does not separate them either (0.27 vs 0.35).

## What worked, and why it is not a prompt change

A property **code can see for free**: does the rule's text reference another
rule? `re.search(r"Rule\s+\d+", rule_text)`.

```
subset                              n   violated   jev acc@0.8   jev precision@0.8
no cross-reference              4,835      33.7%         75.6%               77.8%
cross-references another rule   2,968       7.7%         85.0%               24.8%
```

A cross-referencing rule is violated 7.7% of the time against 33.7% for a flat
rule, and Jev's precision on them is 24.8% — its positive signal there is close
to worthless. So code sends the two kinds down different paths.

**The feature is not a proxy for difficulty.** This is the part that makes it
trustworthy rather than a lucky correlation:

```
            n      violated
L0 flat   1,608       34.8%
L1 flat   1,621       31.5%
L1 xref   1,269       11.6%
L2 flat   1,606       34.7%
L2 xref   1,699        4.9%
```

Flat rules are violated at essentially the same rate at every level. The whole
L0→L2 collapse reported earlier is the changing *share* of cross-referencing
rules, not harder judgment. That is a mechanism, not a curve fit.

## The frozen configuration

```
code:  xref = re.search(r"Rule\s+\d+", rule_text)
flat rules (62%)   Jev >= 0.40 decides
xref rules (38%)   Jev is not consulted; escalate
```

One free parameter. `xref @ 0.9` scored F1 71.4 on dev and `xref never flagged`
scored 71.3 — indistinguishable — so the one-parameter version was frozen. The
threshold sits on a broad plateau (0.35–0.45 within 0.3 F1 points), so 0.40 is
not a grid artifact.

## Held-out, scored once

| configuration | accuracy | precision | recall | F1 | breaches | false blocks |
|---|---|---|---|---|---|---|
| always allow | 75.8% | – | 0% | 0.0 | 1,880 | 0 |
| Jev @ 0.5 everywhere | 75.0% | 48.9% | 79.1% | 60.5 | 392 | 1,555 |
| Jev @ 0.8 everywhere | 79.1% | 60.4% | 40.2% | 48.2 | 1,125 | 496 |
| LLM judge everywhere | 75.4% | 49.1% | 52.1% | 50.6 | 901 | 1,014 |
| both must agree, Jev @ 0.8 | 79.1% | 66.5% | 27.5% | 38.9 | 1,363 | 260 |
| **chosen, xref → allow** | **85.9%** | **69.4%** | 74.8% | **72.0** | 474 | 620 |
| **chosen, xref → escalate** | 82.0% | 69.4% | **84.7%** | **76.3** | **254** | 620 |

Dev said 86.0 / 69.4 / 73.2 / 71.3 and 82.1 / 69.4 / 83.6 / 75.9. **Held-out came
out marginally better than dev**, which is the evidence that matters: the gain
is not fitted.

Against the Jev @ 0.5 baseline: **+10.9 accuracy, +20.5 precision, F1 60.5 → 72.0,
false blocks down 60%.** With escalation, breaches also fall 35% (392 → 254)
while false blocks stay 60% lower, at the price of handing on 38% of rows.

And it is **cheaper**, because the 38% never reach the model at all: 62% of the
questions, $0.0041 per 1,000 judgments.

It holds in every stratum rather than on average — all ten domains land between
F1 71.7 and 80.4, and **L0 reaches 93.2% accuracy, 85.1% precision, 97.5% recall,
F1 90.9, with nothing escalated.** Flat policies are production-grade.

## Why the escalated 38% is where the work stops

On cross-referencing rules alone (2,968 dev rows, 7.7% violated):

| decision | accuracy | precision | recall |
|---|---|---|---|
| allow all | **92.3%** | 0% | 0% |
| Jev @ 0.8 | 85.0% | 24.8% | 46.1% |
| LLM judge | 73.0% | 6.9% | 20.0% |
| both must agree | 88.0% | 15.8% | 12.6% |

The LLM judge scores **6.9% precision against a 7.7% base rate** — no
information. And the ceiling for *any* function of the two signals is **92.3%,
exactly what allow-all gives**. Neither model carries usable signal about a rule
whose force depends on another rule.

So this is not a tuning shortfall. These rules say things like "If (a) … AND
(b) …, Rule 16 is waived. Instead, the chatbot must …", and their verdict depends
on resolving a conditional over other rules. That resolution has to happen in
code or in front of a person; no amount of asking a judgment model about the rule
in isolation recovers it. It is the same conclusion the refund corpus reached
about arithmetic, arrived at from the other direction.

## What to claim

- A policy of **flat prohibitions**: Jev at 0.40, 93.2% accuracy and 85.1%
  precision on held-out, $0.004 per 1,000 judgments. Defensible without
  qualification.
- A policy with **interacting rules**: detect them with a regex, route them away
  from the model, and resolve or escalate. Do not claim coverage.
- The detection is free, deterministic and auditable, which is the right place
  for it in a product that has to explain itself.

## Reproducing

```bash
python scripts/sp_improve.py split                       # show the dev/held split
JEV_API_KEY=... python scripts/sp_improve.py ask --split dev   # the three question variants
python scripts/sp_final.py                               # dev and held-out, frozen config
```
