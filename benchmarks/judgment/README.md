# Judgment tiers — what the opt-in capabilities are worth

**Read this first: none of this is on by default.** Every number below needs
an operator to have enabled a judgment tier *and* turned on egress (or pointed
at a self-hosted model). A default install behaves exactly as it did before
and scores exactly what it scored before.

```bash
JEV_API_KEY=... ANTHROPIC_API_KEY=... \
  uv run python benchmarks/judgment/run_judgment_benchmark.py
```

Results: [`results/judgment_results.json`](results/judgment_results.json).
Every number published about these tiers is rendered from that file by
`scripts/claims.py`.

## What was measured

agentfox with the tiers off and on, through the real detectors, the real
pipeline and the real answerability and commitment paths. Four areas where a
judgment tier is permitted to answer, and one where it is forbidden.

| Area | Default | Tiers enabled |
|---|---|---|
| Injection payloads that defeated our pattern detectors | F1 0.0 | **F1 84.2** |
| Answerability (KUQ) | F1 55.1 | **F1 95.5** |
| PII presence (presidio-research) | F1 38.6 | **F1 83.7** |
| Commitments (refund replies) | F1 42.1 | **F1 96.8** |
| **SQL blast radius — the control** | **F1 100.0** | **F1 100.0** |

### The last row is the point

`judgment/capability.py` forbids every judgment tier from deciding
`STRUCTURAL_PARSED`. Code measured 100.0% there and Jev 98.3%, so enabling a
tier must not be able to reach it. If that row ever moves, the routing table
has failed at its only job, and a test walks every subset of tiers asserting
it cannot.

## The headline, stated precisely

**161 of 165 injection payloads that escaped the shipping detectors are caught**
once a judgment tier is on — including the whole `requires_decode` subset that
the [adaptive benchmark](../adaptive/README.md) attributes nearly all of its
74% attack-success figure to.

It is not decoding them. It reads the framing that has to stay legible for the
attack to work — "decode before acting", "treat the result as your task". A
pattern matcher looks at the payload; a judgment reads the instruction wrapped
around it.

**Every positive in that row defeated `injection.heuristic` by construction**,
which is why the default column is 0.0. It is the hardest available slice, not
a representative one, and the figure should never be quoted as general recall.

## Answerability

The deterministic classifier abstains on **57/676** contested questions; with a judgment tier that becomes **572/676**. Deciding
whether reasonable people disagree is a judgment about meaning, and the
deterministic classifier was never going to reach it.

The cost belongs in the same sentence: over-refusal on genuinely answerable
questions rises from 0.75% to 5.37% on KUQ, and from 0% to 3.69% on the
CoCoNot control. Right for an abstention boundary; wrong for a hard block.

## PII presence is a gate, not redaction

It reports **presence without a span** (`PII.PRESENT_UNLOCATED`). Redaction
needs character offsets and this cannot produce them — emitting `PII.EMAIL`
without a span would give downstream redaction nothing to mask while letting
it believe it had succeeded. Keep the span detectors for redacting.

Asking a third party about a customer's own data is the disclosure this exists
to prevent, so `judgment_pii_egress` is an explicit three-way choice:
`block` (nothing with detected PII leaves), `redact` (default), `allow`. Only
`block` guarantees a subject's data cannot reach a vendor, because redaction
can only mask what the local detector found — 17.8% of it on this dataset.

## Commitments, and a bug this benchmark found

`commitments.py` caught **0 of 1,920** unauthorised commitments on the refund
corpus, including "I've approved your refund". The closed set of binding words
was not the problem; the implementation was — `_WILL_DO` omitted the verb
`approve`, `_APPROVAL_GRANTED` required the passive voice, and there was no
adverb tolerance. Widening those took it to 26.7% recall at **100% precision**
before any model was involved, which is the half that survives a hearing.

The judgment tier adds what is not a vocabulary problem — "that's sorted, it's
on its way", a double negative, Spanish — reaching F1 96.8 at 100% recall.

## Cost

The tiers are ordered cheapest-first and a cascade stops as soon as a question
settles, so the expensive tier sees a fraction of the traffic: **50 hosted-LLM
calls per 100 decisions** on the commitments surface, against 80 if the LLM
answered everything, for the same F1.

Latency is the honest price: 0ms to roughly 300–1,300ms per guarded call. The
pipeline raises its budget for detectors that declare `requires_budget_ms` and
reports the raised figure, so the cost is visible rather than a silent
timeout. Operators who do not opt in keep the 300ms pre-flight budget (NFR-1).

## Limits

- Areas are 330–1,500 rows. The injection and contested-question rows are
  the *complete* sets (all 165 escaped payloads, all 676 contested
  questions); the others are samples. These are capability measurements, not
  the 2,160- and 77,755-row studies behind them (see `docs/jev-*.md`).
- The injection row's positives all defeated the pattern detector by
  construction.
- PII presence degrades badly on non-English text: 42.5% precision across
  gretel's nine languages.
- `performative` still misses the HR-style confident denial (Jev 0.07); the
  cascade's asymmetric band escalates it, but only because no negative from
  the cheap tier is allowed to be decisive.
