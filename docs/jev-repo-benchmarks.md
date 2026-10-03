# Full coverage of the repo's own benchmark estate

All six capability areas now run against Jev. Previously two were done
(action safety, answerability); this completes PII, adaptive, entitlement and
agent security.

| area | rows | judgments | status |
|---|---|---|---|
| `pii/` | 7,221 texts | **88,103** | done |
| `action_safety/` | 6,301 | 6,301 | done earlier |
| `answerability/` | 5,161 | 5,161 | done earlier |
| `adaptive/` | 2,458 | **380 usable** | partial — see below |
| `entitlement/` | 493 | 493 | done, recall-only |
| `agent_security/` | 30 | 30 | done |

Total Jev spend across all six: well under $1.

## PII — the prediction was wrong

I expected Jev to lose here, on the grounds that finding an email address is a
regex problem of the same kind as SQL blast radius. It doesn't.

The committed benchmark scores *spans*. Jev classifies, so the comparison is
reshaped to presence: for each text and each in-scope type, does a span of that
type exist and does the detector say so. 1,500 texts × 10 types, identical rows
for every line.

| approach | accuracy | precision | recall | F1 |
|---|---|---|---|---|
| `pii.native` (regex only) | 92.3% | **98.4%** | 17.3% | 29.4 |
| `pii.presidio.default` (what ships) | 92.3% | 92.5% | 17.8% | 29.9 |
| `pii.presidio.full` (all types on) | 93.4% | 60.5% | 82.5% | 69.8 |
| **jev @0.8** | **97.7%** | 81.0% | **97.9%** | **88.7** |
| both: full AND jev@0.8 | 97.3% | **88.1%** | 81.4% | 84.6 |

**Jev beats every shipping configuration on accuracy, recall and F1 at presence
level**, including `full` with all NER types enabled (F1 69.8 → 88.7). The
default config's 17.8% recall is a policy choice — `DEFAULT_EXCLUDED` removes
PERSON, LOCATION and DATE_TIME, which dominate this dataset's ground truth —
so `full` is the fair capability comparison, and Jev still wins it.

The caveat that decides how to use this: **presence is not spans.** Redaction
needs character offsets, and Jev cannot produce them. So this says Jev is a
strong *gate* — "does this text contain personal data at all" — not a
replacement for a span detector. A gate is a real product surface.

Multilingual is where it degrades: on gretel's 5,594 texts across 9 languages
(72,722 judgments) Jev drops to 87.4% accuracy at 42.5% precision. TAB's 127
court judgments are all-positive on all three types, so they measure nothing.

## Adaptive — Jev catches what our detectors let through

**2,078 of 2,458 rows carry no payload field**, and my first pass scored them
anyway, which meant asking Jev whether the string `"None"` is an injection. It
produced a nonsense result (8.9% on caught attacks, 98.2% on escaped) that was
wrong in a direction obvious enough to catch. Restricted to the 380 rows that
actually carry a payload:

| subset | n | jev @0.5 catches |
|---|---|---|
| all payload-bearing attempts | 380 | 96.6% |
| **escaped our detectors** | 165 | **98.2%** |
| caught by our detectors | 215 | 95.3% |
| └ of escapes: `requires_decode` | 77 | **100.0%** |
| └ of escapes: `readable` | 88 | 96.6% |

The adaptive benchmark's own headline is that the 74% attack-success figure is
almost entirely `requires_decode` — payloads obfuscated so a pattern detector
cannot read them. **Jev catches 100% of those.** It is not decoding anything;
it is reading the framing that has to stay legible for the attack to work —
"decode before acting", "treat the result as your task". A pattern matcher
looks at the payload; the judgment reads the instruction wrapped around it.

That is the most directly useful finding for the product in this whole
investigation.

## Entitlement — Jev fails

493 PrivacyLens over-sharing vignettes. **Recall 18.5% at 0.5, 1.6% at 0.7**,
with median scores of 0.32 and 0.28 on the two questions. The state was not
truncated and the final action was present; Jev simply does not see these as
over-shares.

These are scenarios where an agent reads a lawyer's case notes and posts to
Facebook. Recognising the problem needs a model of who is entitled to what,
which is exactly the structural, grant-based thing `entitlement.py` resolves in
code — and the committed benchmark's 100% recall there is mechanical, by
construction, not a classifier result.

**There are no negative cases in this dataset**, so precision is unmeasurable
and no threshold can be chosen honestly. Reported as recall only.

## Agent security

| tier | n | accuracy | recall | false positives |
|---|---|---|---|---|
| tier_b (indirect injection) | 20 | 65% | 100% | 7 |
| tier_c (tool parameter scope) | 10 | 90% | 80% | 0 |

Catches every injection but flags 7 of 10 benign pages as injections — on 20
rows that is indicative only.

## The line, restated after all six

The structure-versus-meaning split from the earlier work mostly holds, with one
correction and one refinement:

- **Structure, fully parseable** — SQL blast radius. Code 100%, Jev 98.3%.
  Code owns it.
- **Structure, grant-based** — entitlement. Code is exact by construction, Jev
  gets 18.5%. Code owns it.
- **Pattern-shaped but open-ended** — SQLi fragments, PII presence, obfuscated
  injections. **This is where I was wrong.** I classed PII with SQL and
  expected Jev to lose; it wins at presence level, and on adaptive it catches
  100% of the encoded payloads our detectors cannot read. The distinguishing
  feature is not whether the target has structure but whether the *set of
  surface forms is enumerable*. A WHERE clause is enumerable; the ways to wrap
  an instruction around a hex blob are not.
- **Meaning** — contested questions, answerability. Code 8.4%, Jev 81.7%.

## Reproducing

```bash
JEV_API_KEY=... python scripts/pii_run.py      # 7,221 texts, 88,103 judgments
JEV_API_KEY=... python scripts/rest_run.py     # entitlement, adaptive, tiers
python scripts/pii_compare.py                  # vs all 3 shipping configs
python scripts/bench_compare.py                # action safety + answerability
```

`pii_compare.py` needs spaCy's `en_core_web_lg`; install it into the venv with
`uv pip install --python .venv/bin/python <en_core_web_lg wheel url>` or the
presidio configs report as unavailable rather than failing loudly.
