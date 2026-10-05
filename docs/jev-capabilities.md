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

## Who may change this, and from where

Everything above was an environment variable until it was not. That is the
right home for *whether this deployment may talk to a third party at all*: it
is set by whoever runs the process and accepts the risk, and no request can
reach it. It is the wrong home for *whether we want remote judgment on today*,
which somebody decides repeatedly and an auditor later asks the history of. An
environment variable has no author, no reason and no history, and changing one
needs a deploy.

So there are two layers:

| layer | set by | reachable from a request | has history |
|---|---|---|---|
| **deployment ceiling** — `allow_egress`, `judgment_pii_egress`, `judgment_fail_closed` | process environment, TOML | no | no |
| **posture** — which permitted tiers to use, how strictly | admin, in the product | yes | yes, in the audit chain |

The rule between them is one-directional and enforced in
`judgment/posture.py`: **posture may narrow what the deployment permits and may
never widen it.** Enabling `jev` on a deployment with `allow_egress = false`
returns `409` with the reason, rather than storing a preference that silently
does nothing — a settings page showing a hosted tier as enabled while nothing
is sent to it has answered a compliance question wrongly, in writing, in a
screenshot somebody will attach to an attestation.

Three consequences worth stating:

- **Local tiers need no permission.** The ceiling constrains what *leaves*, not
  what runs. A deployment with egress off can still enable `local_model` and
  `local_llm` and get better.
- **Revocation is retroactive.** The ceiling is re-applied on read, so revoking
  `allow_egress` narrows every row written while it was allowed. A stored
  posture is a preference, not a permission.
- **Widening needs saying so twice.** `confirm_egress` is required for any
  change that starts sending payloads off the machine or loosens personal-data
  handling. Turning a hosted tier *off* needs no confirmation: the guard is on
  the direction whose consequence is invisible from the screen that makes it.

`PUT /api/judgment/posture`, write family `judgment_posture`
(owner/admin/security — not `developer`, for the same reason silencing a
detector is not a developer's call). Every change records to the audit chain
under `operator.judgment_posture.changed` with the before/after pair and a
required reason. Policies → Judgment posture is the UI.

With no row stored, settings apply exactly as they did before any of this
existed — which is what keeps the published numbers comparable.

## Tests

`tests/test_judgment_capability.py` (19), `tests/test_judgment_egress.py` (15)
and `tests/test_judgment_posture.py` (24). The ones that matter: no capability
can take a structural decision from code, enabling more never shrinks the
decider set, excluded votes are discarded, hosted tiers drop out on both egress
gates, the table cannot forbid a tier that actually measured best — and posture
cannot enable a tier the deployment forbids, cannot loosen personal-data
handling below the deployment's floor, and cannot survive a deployment that
revokes egress afterwards.
