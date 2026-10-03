# Wiring the first judgment tier into the request path

`capability.py` decides *who may answer what*. This connects it to the live
pipeline for one surface area — indirect prompt injection — and records what
broke when it was first tried.

## Why injection first

It is where the measurement is strongest and where the egress question is
easiest. On the repo's own adaptive benchmark, restricted to the 380 attempts
that carry a payload, Jev flags 98.2% of the 165 that escaped our detectors,
including **100% of the `requires_decode` subset** that accounts for nearly all
of that benchmark's 74% attack-success figure. And the content being judged is
untrusted input from outside, not the customer's own data.

## How it composes

`injection.judgment` is an ordinary detector. It registers like any other,
appears in `enabled_detectors`, and emits the existing
`INJECTION.INSTRUCTION_IN_DATA` / `INJECTION.EXFILTRATION` entities with the
same OWASP and ATLAS ids the heuristic uses — so policies and control mappings
need no change to consume it.

**The union is free.** `PATTERN_OPEN` is the one kind where the benchmarks say
composition wins (91.7% code + 84.6% judgment = 94.9%), and the pipeline
already collects every detector's detections. Adding this detector *is* the
union; no combination code was written.

**It cannot take over anything else.** `available()` asks `CapabilityRouter`
whether a non-deterministic tier may decide `PATTERN_OPEN`. On a parse tree or
a grant lookup the router returns code alone, and the detector is never
selected.

**It is absent by default.** Three things must all be true: the operator lists
a judgment tier in `judgment_tiers`, `allow_egress` is on, and a key is
present. Otherwise `available()` is False and the detector does not exist.

**It fails visibly.** Egress refused, PII gate closed, service down, no key —
all return `status="unavailable"`, not an empty clean result. A detector that
reports "nothing found" after failing to run is worse than an absent one,
because the pipeline cannot tell the difference.

## What broke: the budget

The first working version caught **4 of 40**. The detector was fine in
isolation, scoring 0.92–0.96 on the same payloads. The pipeline was killing it:

```
judgment statuses inside the pipeline: {'timeout': 10, 'ok': 2}
enforcement_budget_ms: 300   detector_timeout_ms: 40
```

A network round trip is ~350ms and the pre-flight budget is 300ms (NFR-1), so
the per-detector allowance — `min(own timeout, remaining budget)` — could never
be enough. **Enabling the tier bought nothing while looking like it had worked**,
which is the worst of the available failure modes: silent, and safe-looking.

The fix is to make the cost explicit rather than to bury it. A detector that
cannot finish inside the default declares `requires_budget_ms`, and the
pipeline raises the budget for that run and reports the raised figure in
`PipelineResult.budget_ms`. An operator who enables a hosted tier is choosing
latency for recall; the system should charge them for it visibly instead of
timing out. Detectors nobody opted into cannot trigger it, so **NFR-1 still
holds for the default install** — pinned by a test.

## Measured through the real pipeline

60 payloads that escaped the shipping detectors, run through
`DetectorPipeline` with both detectors selected:

```
injection.heuristic   caught  0/60     (they escaped it by definition)
injection.judgment    caught 59/60     98.3%
                               421ms per call
```

That 421ms is the honest price of the capability, and it is the number an
operator is agreeing to when they switch the tier on.

## Enabling it

```toml
judgment_tiers    = ["deterministic", "jev"]
allow_egress      = true
enabled_detectors = [..., "injection.judgment"]
```

Plus `JEV_API_KEY`. With `judgment_pii_egress = "block"` (not the default) the
detector will refuse any payload containing detected personal data and report
`unavailable` for it, which is the correct behaviour for regulated deployments
and visibly narrows what the tier covers.

## Still not wired

`semantic` (answerability — 8.4% → 81.7% measured) and the `pattern_open` PII
presence gate (29.9 → 88.7 F1) are the next two. PII needs more care than
injection did: presence is not spans, so it is a gate signal and not a
redaction input, and the payload is the customer's own data rather than
untrusted input — which is the harder egress question, not the easier one.

## Tests

`tests/test_judgment_detector.py` (12): absent by default, absent with the tier
on but egress off, present when both, flags an encoded payload, quiet on
ordinary content, sample redacted, refusal reports `unavailable` rather than
clean, empty content makes no call, reads only externally-sourced surfaces,
unions with the heuristic, raises the budget it needs, and leaves the default
install's 300ms budget alone.
