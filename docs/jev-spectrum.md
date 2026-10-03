# The product with every capability enabled

Not a study of Jev — a measurement of agentfox with and without the judgment
tiers switched on, through the real detectors, the real pipeline and the real
answerability path. The question an operator actually asks: if I turn these
on, what do I get, and what does it cost?

```
area                                 DEFAULT        |   ALL ENABLED        ΔF1   cost/call
injection (escaped payloads)    49.7%   F1  0.0     |  82.4%  F1 84.8    +84.8   0 → 421ms
answerability (KUQ)             38.0%   F1 55.1     |  88.7%  F1 94.0    +38.9   0 → 263ms
PII presence (presidio)         41.0%   F1 36.6     |  81.0%  F1 86.5    +50.0   0 → 367ms
SQL blast radius (regression)  100.0%   F1 100.0    | 100.0%  F1 100.0    +0.0   unchanged
```

The last row is the point of the whole architecture. SQL is **identical by
construction**: `capability.py` forbids every judgment tier from deciding
`STRUCTURAL_PARSED`, so no amount of enabling can reach it. Enabling
everything is safe because the measured failures are enforced, not documented.

The injection row reads oddly until you know the corpus: those are the 165
payloads that *escaped* the shipping detectors, so the heuristic scores 0 by
definition. It is the hardest available slice, not a representative one.

## The three surfaces, and why each is wired the way it is

**`injection.judgment`** — `pattern_open`, union, threshold 0.5. The pipeline
already collects every detector's detections, so adding it *is* the union; no
combination code exists. Surfaces are the ones where content arrives from
outside the trust boundary, deliberately not `output` or `reasoning`.

**answerability** — `semantic`, union, threshold 0.7. Composed *outside*
`answerability.py`, which states on purpose that it is all deterministic. That
principle is about self-assessment — asking the answering model whether it
knows reproduces the overconfidence being guarded against — and a separate,
non-generating judgment model has no answer to defend. The deterministic core
is untouched and stays authoritative: **the judgment layer can only add an
abstention, never remove one.**

**`pii.judgment`** — `pattern_open`, threshold 0.8 rather than 0.5, because it
fires on ordinary customer content rather than on attacks. It emits one
unlocated signal, `PII.PRESENT_UNLOCATED`, and that is deliberate: redaction
needs character offsets and this cannot produce them, so emitting `PII.EMAIL`
without a span would give downstream redaction nothing to mask while letting
it believe it had succeeded.

## The PII egress question, which is the awkward one

Unlike injection, the content here is the customer's own data — asking a third
party about it is the disclosure the detector exists to prevent. Three things
make it defensible, and only together:

- `judgment_pii_egress = "redact"` (default) masks everything the local
  detector found first. Measured: recall on the pairs local *missed* is 98.7%
  redacted against 99.4% unredacted. The gain survives; the found data stays.
- `judgment_pii_egress = "block"` refuses outright for any payload containing
  detected PII — and this has a useful property rather than being merely safe.
  The detector then runs **only on text the local detector thinks is clean**,
  which is exactly the 82% blind spot it exists to cover, and no text with
  known personal data ever leaves. Verified on 60 presidio texts: 10 refused,
  50 sent, 31 of those flagged.
- Nothing runs at all unless a judgment tier is enabled *and* `allow_egress`
  is on.

## What it costs

Latency is the honest price: 0ms → 263–421ms per guarded call, because a
hosted judgment is a network round trip. The pipeline raises its budget for
detectors that declare `requires_budget_ms` and reports the raised figure, so
the cost is visible rather than silent. Operators who do not opt in keep the
300ms pre-flight budget (NFR-1) unchanged.

Precision is the other price, and it is real:

- answerability over-refusal on genuinely answerable questions rises from
  0.75% to 5.37%, and 0% to 3.69% on the CoCoNot control.
- PII presence precision is 81.0% at 0.8 — about one in five flags is wrong.

Both are the right trade for a gate that escalates and the wrong one for a
hard block, which is why these are opt-in and not defaults.

## Reproducing

```bash
JEV_API_KEY=... python scripts/spectrum.py --n 100
```

```toml
judgment_tiers    = ["deterministic", "jev"]
allow_egress      = true
enabled_detectors = [..., "injection.judgment", "pii.judgment"]
judgment_pii_egress = "block"   # or "redact", the default
```

## Still deterministic-only, on purpose

`structural_parsed` (parse trees) and `structural_grant` (entitlement) are
closed to every judgment tier, because code measured 100% and exact against
98.3% and 18.5%. `performative` is routed but has no wired surface yet.
