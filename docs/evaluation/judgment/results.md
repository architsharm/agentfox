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

This is exactly what `python scripts/final_numbers.py` prints.

```
corpus / configuration                    n trivial     acc      prec   recall     F1  breach   fblock    esc      $/1k
SafePyramid (external, 3,000 cases, policy rules)
  jev @0.5, no routing               77,755   76.1%    74.7%     48.3%    78.1%   59.7   4,067   15,577      -     0.007
  CHOSEN xref->allow                 77,755   76.1%    85.9%     69.2%    73.6%   71.3   4,919    6,082      -     0.004
  CHOSEN xref->escalate              77,755   66.3%    82.1%     69.2%    84.0%   75.9   2,600    6,082    38%     0.004
  CHOSEN, unseen 2,400 cases         62,179   66.4%    82.1%     69.2%    84.0%   75.9   2,073    4,858    38%     0.004
  L0 only (no interacting rules)     16,114   65.6%    92.7%     84.5%    96.7%   90.2     183      987      -     0.004

Agent trajectories (external: R-Judge + ATBench + ATBench500 + Claw)
  always block                        2,571   52.3%    52.3%     52.3%   100.0%   68.7       0    1,227      -         0
  2-question set @0.70 (old)          2,571   52.3%    74.9%     90.2%    58.3%   70.9     560       85      -      0.21
  dev: >=2 of 6 signals @0.6          1,285   51.4%    77.7%     74.3%    86.4%   79.9      90      197      -      0.26
  HELD-OUT: >=2 of 6 @0.6             1,286   53.1%    77.4%     74.9%    86.2%   80.2      94      197      -      0.26
  HELD-OUT: 2-question set @0.70      1,286   53.1%    74.8%     91.1%    58.3%   71.1     285       39      -      0.21
  CHOSEN on all 2,571                 2,571   52.3%    77.5%     74.6%    86.3%   80.1     184      394      -      0.26
    R-Judge                             571   52.7%    90.0%     89.9%    91.4%   90.6      26       31      -      0.26
    ATBench                           1,000   50.3%    66.6%     65.3%    70.0%   67.6     149      185      -      0.26
    ATBench500                          500   50.0%    93.6%     88.7%   100.0%   94.0       0       32      -      0.26
    ATBench-Claw                        500   59.2%    69.0%     66.3%    97.0%   78.7       9      146      -      0.26

Refund agent (generated, 2,160 cases, arithmetic predicates)
  R1 whole policy, one judgment       2,160   68.3%    74.0%     87.2%    72.6%   79.2     405      157      -      0.03
  R3 routed: code owns predicates     2,160   68.3%    93.0%     93.7%    96.3%   95.0      55       96      -      0.03
  R3 without `presupposes`            2,160   68.3%    95.5%    100.0%    93.4%   96.6      97        0      -      0.03

Coding / HR / data access (generated, 365 cases)
  coding agent                           93   72.0%    95.7%    100.0%    94.0%   96.9       4        0      -      0.03
  hr screening                          180   66.7%    78.9%     88.7%    78.3%   83.2      26       12      -      0.03
  data access                            92   65.2%    95.7%     93.8%   100.0%   96.8       0        4      -      0.03
  all three                             365   67.7%    87.4%     93.1%    87.9%   90.4      30       16      -      0.03
```

`trivial` is the better of always-allow and always-block on that corpus.
Accuracy is over decided rows, so the escalate rows show a different trivial
baseline from the allow rows. The `$/1k` column is a per-row estimate typed
into `final_numbers.py` from Jev's published price and the prompt sizes, not a
measured bill.

R-Judge by agent category, under the earlier two-question set
(`max(unsafe, irreversible) >= 0.70`), on all 571:

```
category             n      acc      prec   recall      F1
Application        252    94.0%     98.6%    91.6%    95.0
Finance            126    92.9%    100.0%    76.9%    87.0
IoT                 30    53.3%    100.0%    26.3%    41.7
Program            128    84.4%     92.9%    76.5%    83.9
Web                 35    74.3%     92.3%    60.0%    72.7
```

## What the numbers say

**The approach beats the trivial baseline on every corpus, and by most where the
judgment is about a concrete act.** Across 2,571 external agent trajectories the
configuration chosen on a dev half (at least 2 of 6 signals at 0.6) scores
**F1 80.2 on the held-out half** and 80.1 on all of them, against 68.7 for always
blocking. It is strongest on R-Judge (90.0% accuracy) and ATBench500 (93.6%), where
the unsafe thing is an action that appears in the transcript, and weakest on
ATBench (66.6%), where most unsafe trajectories are competence failures rather than
attacks. The earlier two-question set, chosen on R-Judge alone, scores 88.3% at
97.2% precision on R-Judge but recalls only 58.3% across all four corpora.

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

**The held-out half is not clean at the question level.** The four questions added
after the ATBench miss analysis were written from misses across all of ATBench,
held-out half included, so the 80.2 held-out F1 measures the vote rule and
threshold on unseen rows but not the questions. Adding them cost precision
(91.1% → 74.9% on the held-out half) and ATBench-Claw dropped from F1 85.0 to 78.7.

**Unintended harm is harder than injection.** On R-Judge, the earlier two-question
set recalls 98.5% of injection cases and 43.6% of unintended-harm cases
(`docs/jev-agentic.md` (kept outside this repository) has the by-type breakdown for each configuration).

**SafePyramid's precision tops out at 69.2%** on the rows it decides. Roughly
three in ten blocks are wrong. That is a large improvement on 48.3% and still not
good enough to block automatically without review.

## What to claim, and what not to

Claim, with numbers behind it:

- Judging whether an agent **did** something unsafe in a trajectory: F1 80.2 on
  the held-out half of 2,571 external trajectories (precision 74.9%, recall
  86.2%), with the caveat above about how the questions were chosen.
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
export AGENTFOX_JEV_DATA=local/datasets/jev-corpora   # the default; see docs/jev-datasets.md
python scripts/sp_corpus.py --download
JEV_API_KEY=... python scripts/sp_run.py jev --sample 3000     # 77,755 judgments, $0.50
JEV_API_KEY=... python scripts/rj_run.py                       # 571 trajectories, 20s
python scripts/final_numbers.py                                # the table above
```

Every corpus is read from `AGENTFOX_JEV_DATA` (default `local/datasets/jev-corpora`);
`docs/jev-datasets.md` (kept outside this repository) gives the fetch instructions for each.
