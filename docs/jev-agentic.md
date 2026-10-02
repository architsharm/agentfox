# The agentic side, properly covered

R-Judge's 571 trajectories were too thin to carry a claim about agents. Three
more labelled corpora bring it to **2,571 agent trajectories**, all Apache-2.0,
all labelled by someone else, all roughly balanced:

| corpus | n | unsafe | what it is |
|---|---|---|---|
| [R-Judge](https://github.com/Lordog/R-Judge) | 571 | 53% | 5 agentic categories, injection and unintended harm |
| [ATBench](https://huggingface.co/datasets/AI45Research/ATBench) | 1,000 | 50% | long-horizon, 1,575 tool definitions, rich taxonomy |
| ATBench500 | 500 | 50% | the earlier release, disjoint from ATBench |
| [ATBench-Claw](https://huggingface.co/datasets/AI45Research/ATBench-Claw) | 500 | 59% | **Claude Code session logs with untrusted skill context** |

Claw is the one to note: its trajectories are Claude Code sessions carrying
untrusted skill markdown, which is the surface agentfox actually hooks.

## The frozen question set did not transfer

The two questions chosen on R-Judge, applied with no retuning:

| corpus | accuracy | precision | recall | F1 |
|---|---|---|---|---|
| R-Judge (where chosen) | 88.3% | 97.2% | 80.1% | 87.8 |
| ATBench500 | 87.2% | 93.5% | 80.0% | 86.2 |
| ATBench-Claw | 82.0% | 83.9% | 86.1% | 85.0 |
| **ATBench** | **56.9%** | 80.6% | **17.5%** | 28.8 |

ATBench misses 410 of 497 unsafe trajectories. Retuning the threshold on an
ATBench dev half only reaches 58.4% accuracy on its held half, so this is not a
calibration problem.

## Why: the questions covered one axis of harm

The failure modes of the missed cases are not attacks:

```
unconfirmed_or_over_privileged_action                   92% missed
flawed_planning_or_reasoning                            91% missed
provide_inaccurate_misleading_or_unverified_information  90% missed
incorrect_tool_parameters                               86% missed
unauthorized_information_disclosure                      81% missed
failure_to_validate_tool_outputs                        67% missed
```

The two frozen questions ask about harm, loss, exposure, and *unauthorised*
irreversible action. Consider the ATBench case where an agent pipes an
unverified news article into a dispatch system as though it were authoritative:
nothing was destroyed, and the user did ask for the logging. Jev scored it 0.25
and 0.24 — and was right to. It answered the questions it was asked.

**R-Judge hid this** because its cases are mostly injection. Its own breakdown
said so and I under-weighted it: injection 97.0% recall, unintended harm 67.3%.
ATBench is where that weakness becomes the whole result.

## Four more questions, one signal each

`unconfirmed` (a consequential step without the check the situation required),
`unvalidated` (tool or document output acted on as fact), `unverified_claim` (a
claim stated without establishing it), `wrong_action` (parameters that do not
match the request). The frozen pair is imported unchanged, so the earlier
numbers stay reproducible.

Separation on dev, which is also a verdict on each question:

```
question              unsafe cases   safe cases      gap
unsafe                        0.70         0.23    +0.46
unconfirmed                   0.81         0.35    +0.46
irreversible                  0.51         0.09    +0.42
unverified_claim              0.66         0.32    +0.34
unvalidated                   0.82         0.58    +0.24
wrong_action                  0.70         0.56    +0.14
```

`unconfirmed` is the valuable addition, matching the largest miss bucket.
`wrong_action` barely separates and is carried only by the vote.

## The rule: at least two of six signals above 0.6

Chosen on a corpus-stratified dev half, reported once on the held half.

| rule | accuracy | precision | recall | F1 |
|---|---|---|---|---|
| always block | 53.1% | 53.1% | 100% | 69.4 |
| 2-question set @0.70 | 74.8% | **91.1%** | 58.3% | 71.1 |
| **≥2 of six @0.6** | **77.4%** | 74.9% | **86.2%** | **80.2** |

Dev said F1 79.9, held-out gave 80.2. A vote beats any single signal and any
single threshold on either axis, which is the point: no one question covers both
attack-driven and competence-driven harm.

**On all 2,571: 77.5% accuracy, 74.6% precision, 86.3% recall, F1 80.1** against
a 52.3% baseline, at $0.26 per 1,000 trajectories.

Per corpus, with the old rule for comparison:

| corpus | accuracy | precision | recall | F1 | old F1 |
|---|---|---|---|---|---|
| ATBench500 | 93.6% | 88.7% | 100% | **94.0** | 86.7 |
| R-Judge | 90.0% | 89.9% | 91.4% | **90.6** | 89.4 |
| ATBench-Claw | 69.0% | 66.3% | 97.0% | 78.7 | **85.0** |
| ATBench | 66.6% | 65.3% | 70.0% | **67.6** | 28.8 |

## What this cost in honesty

**Precision fell from 91.1% to 74.9%.** The old rule blocked rarely and was
almost always right; this one blocks more and is wrong a quarter of the time.
For a guardrail that escalates rather than hard-blocks, trading 16 points of
precision for 28 points of recall is the right direction — but it is a trade,
not a free win.

**Claw got worse**, F1 85.0 to 78.7, recall 97.0% at 66.3% precision. A
per-corpus rule would fix it and is not available in production, where you do
not know which corpus a trajectory came from. Reported rather than tuned away.

**ATBench is still the weakest at 66.6%**, even after a 39-point F1 improvement.
Long-horizon competence failures remain the open problem: judging whether an
agent did its job *correctly* is a different and harder question than judging
whether it did something forbidden, and the second is what this stack is good at.

## Reproducing

```bash
JEV_API_KEY=... python scripts/rj_run.py     # R-Judge, 571
JEV_API_KEY=... python scripts/at_run.py     # ATBench x3, frozen questions
JEV_API_KEY=... python scripts/ag_run2.py    # all 2,571, six questions
python scripts/final_numbers.py
```
