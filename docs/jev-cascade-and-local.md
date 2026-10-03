# Two corrections: local inference, and not paying for the LLM every time

Both came from using what was merged in #31 and finding it wrong.

## 1. A self-hosted model is not egress

`local_llm` was in the routing table and unusable: `LiteLLMProvider.available()`
required `allow_egress` even when `litellm_base_url` pointed at `localhost`.
Calling loopback crosses no network the customer does not control, so NFR-4 has
nothing to gate — and the effect was that the deployments most likely to want a
self-hosted judge (the ones that had correctly turned egress off) were the ones
that could not have it.

Fixed: the provider is available when a base URL is set **and** egress is on
**or** that URL is loopback.

`is_local_endpoint()` now lives in `providers/base.py` and is the single
definition both layers use. It was previously duplicated in `judgment/llm.py`,
and two copies that drifted would mean a self-hosted model being treated as a
vendor by one layer and not the other.

```
egress OFF, loopback  → provider available: True   tier: local_llm
egress OFF, remote    → provider available: False  tier: llm
```

Fails safe: anything not *provably* loopback is remote, so a malformed URL is
gated rather than exempted.

## 2. Union was paying for the LLM on every decision

The panel asked every enabled tier on every decision and kept the highest
score. That is simple, and on injection it bought **+0.1 F1 for a hosted LLM
call on 100% of traffic**.

`Combine.CASCADE` asks in order and stops as soon as a question is settled;
only the still-unsettled questions reach the next tier, and a tier with
nothing left to answer is never called. Measured on 100 refund replies, all
reaching the same F1 96.8 at 100% recall:

| configuration | LLM calls |
|---|---|
| llm only | 80 / 100 |
| **cascade, llm first** (what #31 shipped) | **80 / 100** |
| cascade, jev first | **50 / 100** |

Asking the LLM first cost everything and bought nothing. Jev leads now.

### The asymmetric band, which is the part that matters

A confidence band catches *uncertainty*, not *error*, and Jev's dangerous
failures on performative work are confident **denials** — 0.07 on an answer
that settles a hire. A symmetric band would let one of those end the cascade
before the tier that can see it is ever asked.

On this corpus presupposition happens to score 0.47 and escalate anyway. That
is luck, not a property, and designing to it would be fitting to the corpus.
So `performative` uses `band=(-1.0, 0.7)`: **no negative from Jev is ever
decisive, only a confident yes is.** Measured cost of that safety, offline:
two extra calls per hundred.

| band | F1 | recall | LLM calls |
|---|---|---|---|
| symmetric 0.3 / 0.7 | 96.8 | 100% | 27 |
| **only a confident yes (-1.0 / 0.7)** | **96.8** | **100%** | **29** |

(Offline simulation over stored scores. The live end-to-end figure is 50/100,
higher because a Jev call that fails returns no answer and correctly
escalates — the saving is real but smaller than the simulation suggests, and
50 is the number to quote.)

## Where each kind now sits

```
structural_parsed   code_wins   deterministic only
structural_grant    code_wins   deterministic only
pattern_open        cascade     det → local_model → jev → local_llm → llm   band 0.2/0.8
semantic            cascade     det → jev → local_llm → llm                 band 0.3/0.7
performative        cascade     det → jev → llm → local_llm                 band -1.0/0.7
```

The deterministic tier leads every cascade and is free, so the cheapest
outcome — it fires and nothing else is asked — is also the most common one on
the surfaces where it is precise.

## On Jev eventually overtaking the LLM

Worth recording as the stated expectation rather than a result: as the corpus
grows, a model trained for calibrated judgment may close the gap on
performative work, at which point the LLM tier becomes a fallback rather than
the answer. Nothing here assumes that, and nothing has to change if it
happens — the ordering is a per-kind table backed by measurements, so it moves
when the measurements do.

## Tests

`tests/test_judgment_llm.py` gains four: a decisive cheap answer never reaches
the expensive tier, an uncertain one is carried onward, a mixed batch sends
only the remainder, and one tier failing degrades to the next.
`tests/test_judgment_capability.py` pins the asymmetric band and that Jev is
asked before the LLM.
