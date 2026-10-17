# Jev against the detectors we actually ship

Every earlier comparison was Jev against another model or against a trivial
baseline. This one is against agentfox's own code, on **11,462 rows the repo had
already sourced and labelled**, with the shipping detector's verdict recomputed
here rather than read off a stored summary.

| area | rows | datasets |
|---|---|---|
| action safety | 6,301 | gretelai/synthetic_text_to_sql, payload-box SQLi, AgentDojo |
| answerability | 5,161 | KUQ (4,782), CoCoNot (379) |

Cost: about $0.15 of Jev, 5 minutes of wall clock.

## The result in one line

The two halves land on opposite sides of the same boundary, and it is the
boundary this whole investigation has been circling:

```
parsed property (SQL blast radius)    code 100.0%   jev 98.3%   keep it in code
pattern-ish (SQLi fragments)          code  91.7%   jev 84.6%   union → 94.9%
meaning (is a question contested)     code   8.4%   jev 81.7%   the model earns it
```

## SQL blast radius — code wins outright, as it should

5,528 statements, 59.3% should block.

| approach | accuracy | precision | recall | false blocks |
|---|---|---|---|---|
| **shipping `analyse_sql()`** | **100.0%** | 100.0% | 100.0% | 1 |
| jev max of signals @0.5 | 84.4% | 79.8% | 98.7% | 819 |
| jev max of signals @0.8 | 98.3% | 99.9% | 97.3% | 4 |
| union code OR jev@0.8 | 99.9% | 99.8% | 100.0% | 5 |

**Jev caught zero of the detector's misses, because there are none.** Whether a
DELETE has a bounding WHERE is a property of the parse tree, and a parser is
simply the right instrument. Adding Jev here buys nothing and, at a 0.5
threshold, costs 819 false blocks.

The failure is concentrated exactly where you would expect. On the adversarial
splits — every row a violation — Jev scores 100%. On `natural_dml`, where only
2–3% are violations, it scores 46–49%: the familiar over-flagging on a low base
rate.

This is the architecture claim confirmed from the losing side, on data we did
not write, against our own code.

## SQLi fragments — code better alone, union better still

156 raw payload fragments, 78.2% malicious.

| approach | accuracy | precision | recall |
|---|---|---|---|
| shipping detector | 91.7% | 100.0% | 89.3% |
| jev @0.5 | 84.6% | 100.0% | 80.3% |
| **union code OR jev@0.8** | **94.9%** | 100.0% | **93.4%** |

Jev catches **9 of the 13 fragments the detector misses, with zero new false
blocks**. That is a free 3.2 points. Neither alone is as good as the pair, which
is what genuinely complementary signals look like.

## AgentDojo — a scope boundary, not a win

617 tool calls, 65 from injection tasks.

The shipping check flags nothing here, and the benchmark README says why: it is
a *syntax-level* check on tool arguments, and AgentDojo's attacker-controlled
values are ordinary-looking IBANs, dates and channel names. Containment happens
at the capability layer instead (see `benchmarks/agentdojo/`, where, with
provenance inferred rather than labelled, session-level taint contains every
evaluable attack pair at a large benign-utility cost). The 617 calls here count
each AgentDojo task once per registered version; 384 are unique.

Jev at 0.5 flags 22 of the 65 with 3 false positives across 552 benign calls.
So it supplies a detection signal where the syntactic control has none by
design. That is worth knowing, but it is **not** "Jev beats our detector" — the
product already contains these at a different layer, and a 33.8% recall
detection signal is not a substitute for that.

## Answerability — the model wins decisively

5,161 questions. The shipping `answerability.py` is a deterministic
declared-boundary classifier.

| approach | accuracy | precision | recall | F1 | over-refusals |
|---|---|---|---|---|---|
| always answer | 74.1% | – | 0% | 0.0 | 0 |
| shipping `answerability.py` | 83.5% | **95.1%** | 38.1% | 54.4 | 26 |
| **jev @0.7** | **93.3%** | 85.6% | **88.8%** | **87.2** | 199 |
| union ship OR jev | 93.5% | 85.0% | 90.9% | 87.8 | 214 |
| both ship AND jev | 83.2% | 97.8% | 36.0% | 52.7 | 11 |

Per category, which is where the story is:

```
label                n    ship recall   jev recall   union
future_unknown     659          68.4%        96.2%   97.6%
controversial      676           8.4%        81.7%   84.3%

over-refusal on answerable questions
known            3,447          0.75%        5.37%   5.80%
coconot            379          0.00%        3.69%   3.69%
```

**`controversial` goes from 8.4% to 81.7% recall.** Whether reasonable people
disagree about a question is a judgment about meaning, and no amount of
structural classification reaches it — the shipping classifier was catching 57
of 676.

The cost is real and should be quoted alongside: over-refusal on genuinely
answerable questions rises from 0.75% to 5.37%, and from 0% to 3.69% on the
CoCoNot control. Seven times more over-refusal for twice the overall accuracy
and a 33-point F1 gain. For an abstention boundary that is very likely the right
trade; for a hard block it would not be.

Note also that `BOTH` reaches **97.8% precision** at 36% recall — if the product
wants a high-confidence abstention path, that is the configuration, not a
threshold change.

## What this settles

The dividing line is not the domain, the vendor, or the prompt. It is **what
kind of thing is being decided**:

- **A property of the text's structure** — does this statement have a bounding
  clause, does this query cross a tenant, is this amount over the limit. Code
  owns it, gets 100%, and a judgment model is a downgrade.
- **A property of what the text means** — is this question contested, did this
  answer settle a refund, does this note rely on a protected characteristic.
  Code gets 8.4% and the model gets 81.7%.
- **In between** — pattern-shaped but open-ended, like SQLi fragments. Run both
  and union them; the two miss different things.

Routing on that distinction is the product. It is now measured on 11,462 rows
of the repo's own benchmark data, against the shipping implementation, rather
than argued from corpora I generated.

## Reproducing

These scripts are kept outside this repository; the commands are recorded so the method is
clear. The judgment-tier figures this repository publishes are re-run with
`benchmarks/judgment/run_judgment_benchmark.py`.

```bash
JEV_API_KEY=... python scripts/as_run.py    # 6,301 action-safety rows
JEV_API_KEY=... python scripts/ans_run.py   # 5,161 answerability rows
python scripts/bench_compare.py             # both tables, detector recomputed
```

The answerability comparison re-runs `classify_answerability()` from
`src/agentfox` directly, so the shipping column is this build's behaviour and
not a number copied from a committed summary.
