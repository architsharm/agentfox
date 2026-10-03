# Capabilities: enable more, get better, never worse

The product is a stack of evaluators an operator switches on. The design
problem is not making it better when everything is enabled — it is making sure
that **enabling everything cannot make anything worse**, because that is the
configuration most people will choose.

A hosted judgment model is a large gain on some decisions and a measured
regression on others. Left to call sites, "use Jev if it's configured" would
take SQL blast-radius analysis from 100% to 98.3% and entitlement from exact to
18.5%. So the routing table is enforcement, not advice.

## The tiers

| tier | what it is | egress | always on |
|---|---|---|---|
| `deterministic` | regex, parsers, grant lookups | none | **yes** |
| `local_model` | PIGuard, Granite Guardian, embeddings | none | opt-in |
| `local_llm` | a self-hosted general model | none | opt-in |
| `jev` | hosted judgment model | **yes** | opt-in |
| `llm` | hosted general model as judge | **yes** | opt-in |

```toml
judgment_tiers = ["deterministic", "local_model", "jev"]
```

`deterministic` is present whether listed or not: it needs no key, no weights
and no network, and some decisions have no other permitted decider.

## The five kinds of decision, and who may answer

| kind | example | code | Jev | who decides |
|---|---|---|---|---|
| `structural_parsed` | does this DELETE have a bounding WHERE | **100.0%** | 98.3% | code alone |
| `structural_grant` | may this caller see this resource | **exact** | 18.5% | code alone |
| `pattern_open` | does this text contain PII; is this an injection | 91.7% | 84.6% | **union** (94.9%) |
| `semantic` | is this question contested | 8.4% | **81.7%** | best available |
| `performative` | does "shall I send the rejection" settle it | 0/96 | 7% | vote, else escalate |

Every number is in `EVIDENCE` in `judgment/capability.py` with its corpus and
sample size, and every exclusion quotes the measurement that caused it:

```python
>>> CapabilityRouter(enabled=ALL, allow_egress=True).plan(DecisionKind.STRUCTURAL_PARSED).why(Tier.JEV)
"98.3% vs code's 100.0% on 5,528 SQL statements; 819 false blocks at 0.5"
```

## The two rules that make the promise true

**1. A tier never decides a kind it measured worse on.** Enabling Jev adds
coverage on semantic and pattern-open work and changes nothing structural.
Pinned by a test that walks *every subset* of tiers and asserts the structural
deciders never change.

**2. Union only where union measured better.** Adding an opinion to a decision
that is already right is how a 100% control becomes a 98% one. `pattern_open`
unions because 91.7% and 84.6% compose to 94.9%; `structural_parsed` does not,
because nothing composes with 100%.

A third, quieter rule: votes from excluded tiers are **discarded at
combination**, so a caller that over-collects cannot reintroduce a forbidden
opinion by passing it in.

## Egress is a hard gate, with a choice

Hosted tiers are dropped — not consulted and ignored, dropped from the plan —
when either gate says no:

- `allow_egress = false` (global, default)
- the payload is classified must-not-leave (per call)

Local tiers keep working in both cases, so the capability degrades instead of
failing.

For personal data specifically there is an explicit three-way choice, because
the right answer differs by deployment:

| `judgment_pii_egress` | behaviour |
|---|---|
| `block` | Nothing with detected PII leaves, redacted or not. The remote judgment is simply not made. **The only setting under which a subject's data cannot reach a vendor.** |
| `redact` (default) | Mask what the local detector finds, send the rest. Costs ~1 point of the recall gain; ~82% of PII is not found locally and still leaves. |
| `allow` | Send as-is. A deliberate downgrade, logged at warning. |

That residual is why `block` exists and why the default is not `allow`:
redaction can only mask what the local detector found, measured at 17.8% of it
on presidio-research.

## What this is worth

With everything enabled and egress permitted, the stack decides each kind with
its best measured evaluator:

```
structural_parsed   code              100.0%
structural_grant    code              exact by construction
pattern_open        code ∪ jev         94.9%   (vs 91.7% code alone)
semantic            jev                93.3%   (vs 83.5% code alone)
performative        llm + jev vote     85.0%   (vs 0% code alone)
```

With nothing enabled it is today's product, unchanged. Every step between is
an addition.

## What is not wired yet

`capability.py` is the routing layer. The evaluators it routes *to* are the
existing detectors plus `JudgmentGateway`; connecting the pipeline to ask the
router before choosing an evaluator is the next change, deliberately separate,
because it alters live behaviour and this does not.

## Tests

`tests/test_judgment_capability.py` (19) and `tests/test_judgment_egress.py`
(15). The ones that matter: no capability can take a structural decision from
code, enabling more never shrinks the decider set, excluded votes are
discarded, hosted tiers drop out on both egress gates, and the table cannot
forbid a tier that actually measured best.
