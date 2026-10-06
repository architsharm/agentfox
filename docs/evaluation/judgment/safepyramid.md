# The approach on a corpus we did not write

600 stratified SafePyramid cases — 20 per domain per level — giving **15,576
rule-level judgments** at 24.0% positive. Jev was asked one Noul per rule,
batched per case; the LLM judge was asked for the violated rule set in one call
per case, which is how a team would actually use it; the learned rung was held
out by domain. Cost of the whole run: **$0.10 for Jev, $2.34 for the judge.**

The short version: **every method is close to the trivial baseline, and most of
the earlier conclusions do not survive.**

## Results

| rung | accuracy | precision | recall | breaches | false blocks | $/1k |
|---|---|---|---|---|---|---|
| always allow | 76.0% | – | 0% | 3,737 | 0 | 0.00 |
| always block | 24.0% | 24.0% | 100% | 0 | 11,839 | 0.00 |
| Jev @ 0.5 | 74.8% | 48.5% | 78.2% | 813 | 3,106 | 0.01 |
| Jev @ 0.7 | 78.7% | 55.3% | 58.0% | 1,570 | 1,751 | 0.01 |
| Jev @ 0.8 | **79.2%** | 59.9% | 39.8% | 2,248 | 996 | 0.01 |
| LLM judge | 75.7% | 49.3% | 52.1% | 1,790 | 2,001 | 0.15 |
| learned, unseen domain | 76.1% | 55.3% | **2.2%** | 3,654 | 67 | 0.00 |
| cascade (Jev abstains 0.3–0.8 → judge) | 77.8% | 53.3% | 61.3% | 1,447 | 2,004 | 0.06 |
| **block only if both agree, Jev @ 0.7** | 79.4% | **62.4%** | 35.6% | 2,407 | 800 | 0.16 |
| block only if both agree, Jev @ 0.8 | 79.1% | **66.2%** | 26.5% | 2,747 | 505 | 0.16 |
| block if either | 71.7% | 45.3% | 86.6% | 501 | 3,902 | 0.16 |

Accuracy is the wrong headline against a 76% base rate, so the real statement is
the operating point: **to catch 78% of violations you must wrongly block 26% of
clean rules.** Nothing here changes that much. Precision never passes 66%.

**The ceiling is low and it is not a tuning problem.** Jev and the judge agree on
11,278 of 15,576 rows (72%) and are right on 84.9% of those. A perfect oracle
resolving every disagreement would reach **89.0%**. Worse, on the 8,438 rows
where both say "no violation", 5.9% are violations — 497 breaches that no
tie-break can recover.

## What actually explains the failure

Not difficulty in general — difficulty of a specific kind.

```
level   rules/case   jev acc   jev prec    llm acc   llm prec
L0            16.1     93.3%      89.2%      81.4%      74.9%
L1            28.8     77.0%      48.9%      75.3%      44.1%
L2            33.0     63.9%      32.3%      73.1%      37.6%
```

**On L0, Jev is excellent** — 93.3% accuracy at 89.2% precision, beating the LLM
judge by 12 points and costing 15× less. L0 rules are flat prohibitions. L1 and
L2 add conditional waivers and rules that override each other ("Rule 16 is
waived if (a) … AND (b) …"), and both rungs collapse. They also **cross over**:
Jev wins by 12 points on L0 and loses by 9 on L2.

The stratum breakdown says the same thing from another angle:

```
stratum             n        jev   llm flags   learned
violated        3,737       0.75       52.1%      0.32
distractor      9,261       0.15       12.9%      0.24
plain allow     2,578       0.48       31.4%      0.13
```

**The designed distractors are easy** — Jev sits at 0.15 on rules built
specifically to look violated. That was the opposite of what I expected. The hard
stratum is `plain`: rules about something the conversation never raised, where
Jev sits at 0.48, a coin flip. It cannot tell "this rule is irrelevant here" from
"this rule was broken".

## Four earlier conclusions that were wrong

**Batching is free, and my first reading of this data said otherwise.** Accuracy
fell monotonically with questions per request — 93.3% at 12–17 questions down to
66.7% at 30–35 — which looked like clear evidence that batching costs accuracy
and that the 512-question capacity test had been measuring something too easy. It
is a confound: SafePyramid's levels raise rule count and rule complexity
together. Holding 60 L2 cases and their 1,968 rules fixed and varying only the
batch size:

```
batch size        accuracy   precision   recall
1 per request        65.7%       33.6%    71.4%
8 per request        64.5%       32.5%    70.1%
all at once          65.3%       33.3%    70.9%
```

Flat. Batching costs nothing; the capacity result stands. `scripts/sp_batch.py` (kept outside this repository).

**Latency was understated by 5×.** 794ms median per request for a real
conversation and ~26 questions, p95 1,620ms — against the 150ms I modelled from
the synthetic sweep. Per judgment it is still cheap, but a single
request is not a 150ms call.

**The learned rung does not transfer across domains at all.** 2.2% recall on an
unseen domain: it predicts "allow" and scores the base rate. Consistent with the
60.6% leave-one-template-out result earlier, and it settles the question — that
rung is a memory of shapes already in your logs, not a model of the policy.

**Routing by policy complexity does not help**, even though the crossover
invites it. Jev below a rule-count cut and the judge above lands at 78.1–78.4%,
below Jev @ 0.8 alone at 79.2%. The crossover is real and the obvious way to
exploit it does not work.

## What survives

**Agreement gating is the one combination that pays.** Blocking only when Jev and
the judge agree takes precision from 48.5% to 66.2% and false blocks from 3,106
to 505, at the cost of recall. Everywhere in this work the hard error has been the
false block, so that is the trade worth having.

**Abstention still beats a single bar**, as it did on the generated corpora: the
cascade at 0.3–0.8 reaches 77.8% against 74.8% for Jev at a single 0.5, and
escalates 35%.

**Jev on flat policies is genuinely good and genuinely cheap** — 93.3% accuracy,
89.2% precision, $0.01 per 1,000 judgments, 12 points better than the judge at
1/15 the cost. That is a real product claim, and it is the only one this corpus
supports without qualification.

## What this means for the product

Scope the claim to the policy shape. A policy of flat prohibitions is well served
by Jev plus agreement gating. A policy whose rules waive and override each other
is not served by anything measured here, including a frontier judge — the 89%
oracle ceiling says the two rungs are jointly blind on the same rows, so adding
a third of the same kind will not fix it. That case needs the rule interactions
resolved in code before any model is asked, which is the same conclusion the
refund corpus reached about arithmetic, arrived at from the opposite direction.

## Caveats

600 of 3,000 cases, stratified; the full corpus would cost about $12 at Haiku
pricing and has not been run. The judge is Haiku 4.5 at temperature 0 asked for a
rule set in one call — a stronger model, or per-rule calls, would change its
numbers and its cost together. The learned rung is MiniLM plus logistic
regression, deliberately the cheapest thing that could work, and a fine-tuned
cross-encoder would be a fairer test of that rung. SafePyramid is chatbot policy
compliance, so the code rung has nothing to own here and routing-to-code is
untested by this corpus.

## Reproducing

These scripts are kept outside this repository; the commands are recorded so the method is
clear. The judgment-tier figures this repository publishes are re-run with
`benchmarks/judgment/run_judgment_benchmark.py`.

```bash
python scripts/sp_corpus.py --download
JEV_API_KEY=...       python scripts/sp_run.py jev    --sample 600
ANTHROPIC_API_KEY=... python scripts/sp_run.py llmset --sample 600
                      python scripts/sp_compare.py
JEV_API_KEY=...       python scripts/sp_batch.py --cases 60 --level L2
```
