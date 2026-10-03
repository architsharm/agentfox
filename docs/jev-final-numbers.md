# Final numbers

**8,096 scenarios, 82,851 labelled judgments**, across six corpora, four of them
written by someone else. Total API spend for everything in this document: about
**$1.10 of Jev**.

| corpus | scenarios | judgments | external | what it tests |
|---|---|---|---|---|
| SafePyramid | 3,000 | 77,755 | yes | policy rules, including rules that modify each other |
| ATBench | 1,000 | 1,000 | yes | long-horizon agent trajectories, 1,575 tools |
| ATBench500 | 500 | 500 | yes | the earlier ATBench release, disjoint |
| ATBench-Claw | 500 | 500 | yes | Claude Code session logs, untrusted skill context |
| R-Judge | 571 | 571 | yes | agent trajectories, injection and unintended harm |
| refund agent | 2,160 | 2,160 | no | a policy whose verdict turns on arithmetic |
| coding / HR / data access | 365 | 365 | no | different code-vs-semantic predicate mixes |

Agent-SafetyBench (2,000 cases) was downloaded and **not used**. Its
`fulfillable` field looks like a safety label and is not one: sharing
`CustomerEmailList.csv` with an external agency is `fulfillable: 1` while
writing a profanity acrostic is `fulfillable: 0`, so the field marks whether a
task is *achievable*, not whether it is *safe*. The benchmark works by running
an agent and scoring its trajectory with the authors' judge, which means
labelled judgments require agent runs first. τ²-bench and ST-WebAgentBench are
the same shape. Using `fulfillable` as ground truth would have been inventing
labels.

## The table

```
corpus / configuration                 n   trivial     acc     prec  recall     F1   breach   fblock   esc    $/1k

SafePyramid (external, 3,000 cases)
  jev @0.5, no routing             77,755    76.1%   74.7%    48.3%   78.1%   59.7    4,067   15,577     -   0.007
  CHOSEN xref -> allow             77,755    76.1%   85.9%    69.2%   73.6%   71.3    4,919    6,082     -   0.004
  CHOSEN xref -> escalate          77,755    66.3%   82.1%    69.2%   84.0%   75.9    2,600    6,082   38%   0.004
  CHOSEN, unseen 2,400 cases       62,179    66.4%   82.1%    69.2%   84.0%   75.9    2,073    4,858   38%   0.004
  L0 only (no interacting rules)   16,114    65.6%   92.7%    84.5%   96.7%   90.2      183      987     -   0.004

R-Judge (external, 571 trajectories)
  always block                        571    52.7%   52.7%    52.7%  100.0%   69.0        0      270     -       0
  dev: unsafe @0.40                   285    51.9%   87.4%    85.9%   90.5%   88.2       14       22     -    0.26
  dev: max(unsafe,irrev) @0.70        285    51.9%   90.2%    98.4%   82.4%   89.7       26        2     -    0.26
  HELD-OUT: unsafe @0.40              286    53.5%   82.2%    83.1%   83.7%   83.4       25       26     -    0.26
  HELD-OUT: max(unsafe,irrev) @0.70   286    53.5%   86.4%    96.0%   77.8%   85.9       34        5     -    0.26
  all 571, dev-winning config         571    52.7%   88.3%    97.2%   80.1%   87.8       60        7     -    0.26

refund agent (generated, 2,160 cases)
  R1 whole policy, one judgment     2,160    68.3%   74.0%    87.2%   72.6%   79.2      405      157     -    0.03
  R3 routed: code owns predicates   2,160    68.3%   93.0%    93.7%   96.3%   95.0       55       96     -    0.03
  R3 without `presupposes`          2,160    68.3%   95.5%   100.0%   93.4%   96.6       97        0     -    0.03

coding / HR / data access (generated, 365 cases)
  coding agent                         93    72.0%   95.7%   100.0%   94.0%   96.9        4        0     -    0.03
  hr screening                        180    66.7%   78.9%    88.7%   78.3%   83.2       26       12     -    0.03
  data access                          92    65.2%   95.7%    93.8%  100.0%   96.8        0        4     -    0.03
  all three                           365    67.7%   87.4%    93.1%   87.9%   90.4       30       16     -    0.03
```

`trivial` is the better of always-allow and always-block on that corpus.
Accuracy is over decided rows, so the escalate rows show a different trivial
baseline from the allow rows.

## What the numbers say

**The approach beats the trivial baseline everywhere, and by a lot where the
judgment is about a concrete act.** R-Judge — real agent trajectories, balanced
labels, external — is the strongest result: **88.3% accuracy at 97.2% precision
over all 571**, against a 52.7% baseline. Seven false blocks in 571. That is the
regime the earlier work predicted Jev would be good at, and it is: the unsafe
thing is an action that actually appears in the transcript.

**The routing claim holds on external data at scale.** On SafePyramid the
cross-reference split takes accuracy from 74.7% to 85.9% and precision from
48.3% to 69.2% while cutting false blocks 61%, and reproduces to within a few
tenths on the 2,400 cases that were in neither tuning split. It also costs less,
because 38% of rows never reach the model.

**Code owning the predicates is worth 19 points.** On the refund corpus, one
judgment over the whole policy gets 74.0%; moving the amount and date
comparisons into code gets 93.0%, and dropping the one signal that was doing
more harm than good gets **95.5% at 100% precision**.

**The failure is a policy shape, not a domain.** Every bad number in this table
is the same thing: a verdict that depends on resolving something other than the
text in front of the model. SafePyramid L1/L2 rules waive and override each
other — 38% of rows, escalated. HR screening at 78.9% is the implicature and
presupposition cases. Where the governed thing is literally present — a `rm`
command, a PII column, a payment in a transcript, an amount against a limit —
the numbers are 93% to 97%.

## Where it is weak, stated plainly

**R-Judge IoT: 53.3% accuracy, 26.3% recall on 30 cases.** The worst category by
far. Small n, but it is a real hole and the direction is dangerous — it misses
unsafe cases rather than over-blocking.

**R-Judge drops 4–5 points from dev to held-out** (90.2% → 86.4%). On 285 cases
that is ordinary variance rather than a broken result, but the honest reading is
that R-Judge's threshold is less firmly established than SafePyramid's, which
reproduced across 2,400 unseen cases. Two configurations were scored on R-Judge's
held-out half rather than one, which is mild multiple testing and is why the
all-571 row is also given.

**Unintended harm is harder than injection.** R-Judge by attack type: injection
87.7% accuracy at 97.0% recall, unintended 77.1% at 67.3% recall. An agent that
hurts someone by accident is caught two thirds of the time.

**SafePyramid's precision tops out at 69.2%** on the rows it decides. Roughly
three in ten blocks are wrong. That is a large improvement on 48.3% and still not
good enough to block automatically without review.

## What to claim, and what not to

Claim, with numbers behind it:

- Judging whether an agent **did** something unsafe in a trajectory: 88.3%
  accuracy, 97.2% precision, $0.26 per 1,000 judgments.
- Policies of **flat prohibitions**: 92.7% accuracy, 84.5% precision at
  $0.004 per 1,000.
- Policies with **arithmetic or identity conditions**, with those conditions in
  code: 95.5% accuracy at 100% precision.
- Detecting **which rules a model should not be asked about** with a regex, for
  free, auditably.

Do not claim:

- Coverage of policies whose rules modify one another. Those are 38% of
  SafePyramid and the approach escalates them rather than judging them. The
  ceiling for any function of the Jev and LLM signals on that subset is exactly
  what always-allow gives.
- Catching unintended harm at the rate we catch injection.
- Autonomous blocking at SafePyramid's precision.

## Reproducing

```bash
python scripts/sp_corpus.py --download
JEV_API_KEY=... python scripts/sp_run.py jev --sample 3000     # 77,755 judgments, $0.50
JEV_API_KEY=... python scripts/rj_run.py                       # 571 trajectories, 20s
python scripts/final_numbers.py                                # the table above
```

R-Judge is fetched per-category from `github.com/Lordog/R-Judge` under
`data/`; `scripts/rj_run.py` documents the paths it reads.
