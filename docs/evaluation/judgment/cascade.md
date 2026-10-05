# A routed cascade: code → Jev → learned → LLM

The earlier work asked which single representation was best and treated a miss
as a verdict on the whole approach. That is the wrong frame. No rung here is
good at everything, and the rungs fail in different places — so the question is
not which one wins but when each one is allowed to stop.

## Order the rungs by cost, not by capability

| rung | $/case | latency | good at | blind to |
|---|---|---|---|---|
| code / regex | 0 | ~0.1ms | arithmetic, identity, literal patterns | anything about meaning |
| Jev | $0.0000039 | 794ms median per request* | things literally present in the text | what an utterance *performs* |
| learned (MiniLM + LR) | 0 (local) | ~5ms | shapes it has seen before | shapes it has not |
| LLM judge (Haiku 4.5) | ~$0.0008 | 1,086ms median per request* | performative and implied meaning | structured text; over-flags SQL |

\* Measured on the same 600 SafePyramid conversations, one request per conversation (Jev
scores every rule question in one batched call; the LLM returns the list of violated rules):
Jev p95 1,620ms (`scripts/sp_jev_results_600.json` (kept outside this repository)), Haiku p95
2,021ms (`scripts/sp_llmset_results.json` (kept outside this repository)). On the full 3,000-conversation run Jev's median
was 1,427ms and its p95 3,468ms (`scripts/sp_jev_results.json` (kept outside this repository)). The earlier ~150ms figure
was modelled from a synthetic sweep and is retracted in `docs/jev-safepyramid.md` (kept outside this repository). The
code and learned-rung latencies are estimates, not measurements.

Regex belongs at the **top**, not the bottom. It is the cheapest rung and the
only one that is ever certain; running it last means paying for three models
before asking a question any of them could have skipped. That is the one change
to the proposed order — the rest of the ladder is as described.

The learned rung is MiniLM embeddings plus logistic regression, both local and
Apache-2.0. Granite Guardian and the cached prompt-injection models were the
obvious candidates and are the wrong tool: no general safety model knows whether
"when shall I send the offer paperwork" states a hiring decision under *this*
policy. A model fitted to the policy's own labelled history does.

## Two mechanisms, not one

**Abstention.** A rung may stop the cascade only inside a band where it is
calibrated. Outside that band it abstains and the case descends. Because the
order is cost-ascending, every early stop is money not spent.

**Skipping.** The router may remove a rung entirely when it knows that rung is
blind to this shape of case.

The second is not redundant, and the reason is the whole point:

```
corpus   template           jev p    what the band does
hr       presup_hire         0.07    STOPS -> breach
hr       presup_reject       0.23    abstains, descends, saved
refund   presupposition      0.49    abstains, descends, saved
```

Confidence gating rescues a blind spot only when the model was *unsure*. Jev
scores 0.07 on an answer that settles a hire — confidently wrong, below the
band, so the cascade stops and allows it. No threshold reaches that. Only
knowing not to ask Jev does.

## Results, three domains, 365 cases

| approach | accuracy | breaches | false blocks | escalated | $/1k | avg ms |
|---|---|---|---|---|---|---|
| Jev alone | 87.4% | 30 | 16 | 0 | 0.004 | 150 |
| learned alone (novel shape) | 66.8% | 27 | 94 | 0 | 0.000 | 5 |
| LLM judge alone | 85.5% | 6 | 47 | 0 | 0.800 | 1500 |
| cascade, fixed order | 90.1% | 14 | 22 | 0% | 0.168 | 435 |
| **cascade, routed** | **94.0%** | **6** | **14** | 8% | 0.182 | 435 |

The routed cascade beats every single rung on accuracy while costing **4.4×
less than the LLM judge** and running **3.4× faster**. Where it stops:

```
jev       45%      code      16%
llm       22%      learned    9%      escalate 8%
```

## The transfer test, which is the part worth reading

Those router patterns were written after seeing which templates broke. That is
fitting, and the 94.0% cannot be trusted on its own. So the router and bands
were frozen and run against the 2,160-case refund corpus they had never seen.

| approach | accuracy | breaches | false blocks | $/1k | avg ms |
|---|---|---|---|---|---|
| Jev alone | 77.0% | 0 | 69 | 0.004 | 150 |
| learned alone | 69.0% | 0 | 93 | 0.000 | 5 |
| LLM judge alone | 70.0% | 3 | 87 | 0.800 | 1500 |
| **cascade, fixed order** | **90.3%** | **0** | 29 | 0.148 | 421 |
| cascade, routed | 89.3% | 0 | 32 | 0.156 | 429 |

**The cascade transfers: +13 points over the best single rung, zero breaches,
at a fifth of the LLM's cost.** That result was not fitted to this corpus.

**The router does not transfer, and slightly hurts.** It correctly identified
all 15 `presupposition` cases — the exact shape Jev misses — but routing them
away from Jev made things marginally worse, because abstention had already
solved them: Jev scores 0.49 there, lands in the band, and descends on its own.

So the two mechanisms have a clean division, and it is the opposite of what the
headline number suggested:

- **Abstention does nearly all the work.** It is domain-independent and needs no
  knowledge of how a rung fails.
- **The router earns its place only on blind spots the rung is confident about.**
  In HR that is real and worth 3.9 points. In refunds there were none, and the
  router was dead weight.

Build the router from *observed confident failures*, not from a taxonomy of case
shapes. Anything the model is merely unsure about, abstention already handles.

## A bug the transfer test caught

The first version treated "code says not authorised" as a certain block. True in
two domains — a command aimed at production, a query escaping its tenant — and
false for refunds, where lack of authority only matters if the agent went on to
promise something. An unauthorised agent that correctly explains the queue has
breached nothing. The first transfer run blocked nearly everything and scored
69.7%; separating the two meanings took it to 90.3%.

The distinction is now explicit in `jev_cascade.py` as `CODE_VIOLATION` versus
`CODE_AUTHORITY`. Collapsing them is what makes a cascade block whatever it is
unsure about.

## What is still wrong

All 29 remaining false blocks on refunds are `process_only` and
`explains_policy`, where the LLM judge scores 0.75–0.85 on answers that describe
a process without promising anything. That is the LLM's own blind spot and the
exact mirror of Jev's — Jev scores those 0.31–0.60, more nearly right. The
ladder currently gives the LLM the last word, which is wrong for this shape.

The learned rung's two numbers should be read as a range, not a result:

```
                  seen shapes    novel shapes
coding agent         81.7%          67.7%
hr screening         97.8%          60.6%
data access          91.3%          73.9%
```

It is a memory of past incidents, excellent on shapes already in your logs and
worse than the base rate on new ones. It should terminate the cascade only for
cases close to its training set; that gate is not implemented yet.

Latency is modelled from a single measurement per rung, not from a load test,
and the LLM figures are Haiku 4.5 at temperature 0 — a stronger judge would
change the top rung's cost and accuracy together.

## Reproducing

```bash
JEV_API_KEY=...       python scripts/jev_domains_run.py     # Jev rung
ANTHROPIC_API_KEY=... python scripts/jev_llm_judge.py       # LLM rung
                      python scripts/jev_learned.py         # learned rung, LOTO
                      python scripts/jev_cascade.py         # three domains
ANTHROPIC_API_KEY=... python scripts/jev_cascade_transfer.py --sample 300
```
