# The guardrail must not be the breach

A PII detector that posts the text to a third party to ask whether it contains
PII has not protected anything. It has performed the disclosure it was
installed to prevent, and added a second copy of the data in someone else's
logs. The same is true less obviously everywhere else: asking a hosted model
whether a support reply leaks a customer's address puts the address in the
question.

An internal PII benchmark of the hosted judgment model sent 7,221 texts of synthetic
personal data to `api.typesafe.ai`. That was fine for synthetic benchmark data
and would be a serious defect in the product.

## What was actually wrong

`JevClient` (`detection/judgment/jev.py`) never checked `allow_egress`. Every other
outbound caller in this codebase does — `providers/remote.py`,
`providers/enterprise.py`, `core/webhooks.py`, `monitoring/alerts.py` — and
`detection/adapters/presidio.py` already carries a docstring about
this exact failure, from the time a dependency downloaded a 400MB model from
inside a guarded request:

> `allow_egress` was false throughout; it gates our own outbound calls and
> never saw this one.

That is the same bug a second time. The product default is zero egress, and
judgment quietly wasn't covered by it.

## The design

Three backends, chosen by the operator, defaulting to the safe one.

| `judgment_backend` | behaviour |
|---|---|
| **`local`** (default) | Nothing leaves the process. Questions no local detector covers return UNKNOWN, which the router already treats as *not authorised*. |
| `remote` | May call the hosted model — but only with `allow_egress` on, and only after redaction. |
| `auto` | Local where a local detector covers the question, remote for the rest, under the same gate. |

Plus `judgment_redact_before_egress` (default on) and `judgment_fail_closed`
(default on).

**`JudgmentGateway` is the only thing product code should call.** It is what
holds the gate and the redaction; calling `JevClient` directly skips both,
which is how this arose. As defence in depth the client now refuses on its own
when `allow_egress` is off, so the bypass cannot silently reach the network.

**`EgressRefused` subclasses `JevUnavailable` deliberately.** The router
already treats unavailability as UNKNOWN and never as a pass, so a refusal
degrades along the path that was already tested to fail safely, rather than
needing a second one that might forget.

### What leaves, when remote is permitted

Before any payload goes out, the local PII detector runs over every string in
the state and its findings are masked in place:

```
{"note": "Contact bob@example.com, SSN 123-45-6789, about order 4471",
 "api_key": "sk-live-..."}

                            ↓

{"note": "Contact <PII.EMAIL>, SSN <PII.US_SSN>, about order 4471",
 "api_key": "<redacted>"}
```

Field names matching `password|secret|token|api_key|credential|…` are dropped
by name regardless of what the detectors say — a credential is not an entity
type, so no entity detector is looking for it.

If redaction is on and the detector cannot load, **nothing is sent**. "We could
not check" has to mean "we do not send"; an unverified payload is the case this
module exists to prevent.

## Does redaction defeat the point?

For PII it looks circular — if the local detector already found it, why ask
anyone? It isn't, because the value of remote judgment here is in what local
*misses*: 17.8% presence recall locally against 97.9% for Jev. Masking what
local *found* should leave the rest untouched.

Measured rather than asserted, on 400 presidio texts with every
locally-detected span masked first:

```
on the 311 (text, type) pairs the local detector MISSED
  @0.5   redacted recall 98.7%   unredacted 99.4%
  @0.8   redacted recall 97.1%   unredacted 98.4%
```

**The recall gain survives redaction almost entirely** — about a point — while
the data the local detector found never leaves. That is what makes offering a
remote backend defensible at all.

## What this does not fix

Redaction can only mask what the local detector finds, and on this dataset that
is 17.8% of it. The other 82% still leaves the box in remote mode. For PII
specifically that means:

- `local` is the right default and the only mode to recommend for regulated
  data, even though it is the weaker detector.
- `remote` buys a large recall gain and should be an explicit, informed
  opt-in — the operator is trading disclosure of the text for detection of
  what their own tooling misses.
- The gateway makes that trade visible (`inspect()` reports what would be sent
  and how much was masked) rather than making it silently.

Free-text fields are also only as redactable as the entity set. A name written
in an unusual script, or a case reference that identifies someone in context,
is not something `NativePiiDetector` will mask.

## Tests

`tests/detection/judgment/test_judgment_egress.py`: default sends nothing, remote is
refused with egress off, PII and secret fields are masked, nested structures
are walked, a missing redactor fails closed, a *faulting* redactor fails closed,
`inspect()` reports without sending, and the client refuses on its own when the
gateway is bypassed.

## Configuring it

```toml
# the default: judgment never leaves the process
judgment_backend = "local"

# to allow remote judgment, both of these are required
allow_egress = true
judgment_backend = "remote"

# on by default; turning either off is a deliberate downgrade
judgment_redact_before_egress = true
judgment_fail_closed = true
```
