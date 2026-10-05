# F1 — answerability & abstention, benchmarked

**First answerability datasets built** (see `docs/evaluation/dataset-sourcing.md`). Scores `src/agentfox/grounding/answerability.py` — a **declared-boundary** system, not a generic unanswerable-question classifier: `classify_answerability(text, boundary)` only refuses a question type the operator hasn't declared answerable. Both benchmarks here use exactly the boundary the system defaults to out of the box (`declare_boundary()`'s own fallback when `answerable_types` isn't specified: `["fact", "aggregate", "procedure"]`, no coverage window, no topic/entity restriction) — not a boundary tuned to make either benchmark look better.

1. [KUQ (Known-Unknown Questions)](https://huggingface.co/datasets/amayuelas/KUQ) (MIT) — 4,782 rows across `future_unknown`, `controversial`, and `known` categories. Recall test for the PREDICTION/OPINION classifiers and the over-refusal control.
2. [CoCoNot](https://huggingface.co/datasets/allenai/coconot) `contrast` split (MIT) — 379 rows, real-world-shaped prompts about safety/completeness/modality that have nothing to do with knowledge boundaries. Pure over-refusal/robustness control.

```bash
uv run python benchmarks/answerability/fetch_kuq.py
uv run python benchmarks/answerability/run_kuq_benchmark.py

uv run --with pyarrow python benchmarks/answerability/fetch_coconot.py
uv run python benchmarks/answerability/run_coconot_benchmark.py
```

## Dataset 1 — KUQ (Known-Unknown Questions)

4,782 rows kept from `knowns_unknowns.jsonl`'s 6,884 (the smaller, Turk-curated file — `unknowns_all.jsonl`, a larger GPT-augmented expansion in the same repo, wasn't used but is noted as available for a bigger future run). Three categories in scope:

- `future_unknown` (659 rows) — future-tense questions. Expected: `question_type()` classifies as `prediction`.
- `controversial` (676 rows) — debatable/subjective questions. Expected: classifies as `opinion`.
- `known` (3,447 rows) — ordinary, answerable factual questions. The over-refusal control.

Dropped as out of scope: `ambiguous`, `counterfactual`, `false assumption`, `unsolved problem` (437+520+577+568 = 2,102 rows) — none of these are about whether *the system* holds the answer, which is the only thing `answerability.py`'s declared-boundary design claims to check; they're about the question's own epistemic shape (false premises, unanswerable-in-principle), a different capability this system doesn't model.

### Results, all 4,782 rows

| Category | Support | Metric | Before | After round 1 | Current (`results/kuq_summary.json`) |
|---|---|---|---|---|---|
| `future_unknown` | 659 | Recall | 39.0% | 69.0% | **68.4%** |
| `controversial` | 676 | Recall | 0.74% | 5.62% | **5.77%** |
| `known` | 3,447 | Over-refusal rate | 0.90% | 0.99% | **0.75%** |

Every fix below was chosen on these same KUQ rows, so the current column is a tuned number, not a
held-out one. Round 2 explains the two moves after round 1.

Full breakdown, including per-category `question_type()` confusion counts and miss examples: [`results/kuq_summary.json`](results/kuq_summary.json).

### Fixes applied — both against a real, quantified precision cost, not blind widening

Both `PREDICTION_MARKERS` and `_OPINION_MARKERS` were widened in `src/agentfox/grounding/answerability.py`, but only after testing every candidate directly against `future_unknown`/`controversial` (recall) **and** `known` (false-positive cost) — and, for `PREDICTION`, against CoCoNot's 379 unrelated real-world prompts too, since that's the closer proxy for "does this fire on ordinary text that has nothing to do with a forecast."

**`PREDICTION`** — the old `will`-based marker (`\bwill\s+(?:\w+\s+){0,3}(?:be|become|reach|grow|fall|rise|drop|increase|decrease)\b`) required the verb within 3 words of "will" **and** on a 9-word whitelist. 578 of 659 `future_unknown` questions (87.7%) contain "will" somewhere, but most use a verb outside that whitelist (`"what challenges will *arise*"`, `"how will the use of X *evolve*"`) or have the verb too far away (`"how will the use of digital art in packaging design evolve"` — 7 words between "will" and "evolve"). Four candidates were tested:

| Candidate | Recall on `future_unknown` | FP on `known` |
|---|---|---|
| Old (shipped before this round) | 32.0%* | 0.35%* |
| Wider verb list only | 44.0% | 0.49% |
| Bare `will` + any following word | 87.7% | **1.02%** |
| **Shipped: structural markers** (question-initial `"Will..."`, `"when will"`, `"N years from now"`, `"in N years"`) | **69.0%** (full pipeline) | **0.99%** (full pipeline) |

\* *Isolated to just the old `will`-marker pattern; the 39.0% headline number is the full pipeline including the year/forecast markers already in place.*

The bare-`will` candidate had the highest raw recall but was rejected — it fires on *any* sentence containing "will" plus one more word, which is exactly the kind of change that looks safe against a trivia-question benign set and still misfires on ordinary operational agent traffic ("will my order ship today," "will you send the report") this benchmark has no examples of. **Shipped instead**: five narrow, structural patterns — a question starting with `"Will"` (the inverted yes/no future-question shape), `"when will"`, and three explicit relative-future phrasings (`"N years from now"`, `"in N years"`, spelled-out variants). These are corroborating *shapes*, not a broadened verb vocabulary, so they don't fire on the same class of ordinary "will" usage a wider verb list or a bare match would. Net result: full-pipeline recall 39.0% → 69.0% for a 0.09-point rise in over-refusal (0.90% → 0.99%, 14 new false positives out of 3,447 — see below for what those look like) and **zero new false positives on CoCoNot's 379 unrelated real-world prompts**, which stayed at exactly 0.0%.

**`OPINION`** — five new patterns target third-person subjective/debatable framing that KUQ's `controversial` category actually contains: comparative claims (`"X better/worse than Y"`), normative/deserve framing (`"deserves to"`, `"should X have/get/deserve"`), `"belongs on"`, and moral-judgment framing (`"is it right/wrong/fair/moral/ethical to"`). Recall 0.74% → 5.62% (33 new true positives) for 1 new false positive out of 3,447. **A real ceiling remains, disclosed rather than papered over**: most of KUQ's debatable questions (`"Does pineapple belong on pizza?"`, `"Can a bus driver drive a train?"`) carry no syntactic marker of any kind — their subjectivity is a matter of world knowledge a pattern can't reach. Closing that gap needs actual language understanding, not more regexes; the fix here captures the structurally-detectable slice of the problem and stops there rather than reaching for over-broad markers just to move the number further.

### The 14 new false positives on `known`, inspected directly

Widening `PREDICTION` cost 14 additional over-refusals (0.90% → 0.99%). Spot-checked rather than assumed acceptable: the two clearest examples are `"2012 studies estimated what percentage of mammals could be extinct in 20 years?"` (genuinely asks about a study's *forward-looking estimate* — arguably prediction-shaped despite KUQ's "known" label, since it's citing someone else's forecast) and `"When will organomagnesium halide formation fail?"` (a genuine miss — a chemistry-conditions question that happens to match `"when will"`). Both are real, narrow, low-frequency edge cases rather than a systemic new failure mode.

### Methodology notes

- **Both `classify_answerability()`'s `answerable` boolean and the raw `question_type()` output are scored** — for this boundary (no coverage/topic/entity restriction, no `known_entities` supplied), they're the same decision by construction, so agreement is exact; both are reported so the per-category `question_type()` breakdown is visible directly.
- **No database session used** — `KnowledgeBoundary` is instantiated directly as a plain Python object (never persisted), since `classify_answerability()` only reads its attributes and never queries the database itself.
- Ground truth here is the dataset's own category labels, not derived from a parser or regex — no circularity risk.

---

## Dataset 2 — CoCoNot `contrast` split

379 real-world-shaped prompts CoCoNot's own authors designed as should-comply counterparts to its main refusal-worthy set — a prompt that superficially resembles something a well-behaved assistant might decline, but shouldn't. None are about knowledge boundaries (CoCoNot's categories — safety concerns, incomplete requests, unsupported/modality-limited requests — are a different capability, governed elsewhere in AgentFox or not modeled at all), which is exactly what makes this a clean negative control: any `answerable=False` verdict here is unambiguously the deterministic classifiers misfiring on ordinary text, not a scope disagreement the way KUQ's `controversial` category is.

### Results, all 379 rows

**Over-refusal rate: 0.0% (0/379).**

| Category | Support | FP |
|---|---|---|
| Requests with safety concerns | 149 | 0 |
| Incomplete requests | 148 | 0 |
| Unsupported requests | 82 | 0 |

Full breakdown: [`results/coconot_summary.json`](results/coconot_summary.json).

A clean pass — the `PREDICTION`/`OPINION`/`AGGREGATE`/`PROCEDURE` regexes never fire on any of these 379 prompts, despite them spanning dangerous-topic phrasing, false presuppositions, underspecified requests, and modality-limited requests (`"draw me a picture of..."`-style asks a text-only boundary check has every opportunity to misfire on and doesn't).

### Methodology notes

- Same boundary, same direct-call methodology as Dataset 1.
- All 379 rows are, by construction, "should comply" — this is a pure false-positive measurement, not a precision/recall pair; there's no positive class to measure recall against in this split.

---

## What this round found and fixed

Both `PREDICTION` and `OPINION` recall were real, fixable gaps, not just benchmark artifacts — and both were widened in `src/agentfox/grounding/answerability.py` using structural markers chosen specifically to avoid the overfitting risk a blanket verb-list or keyword expansion would carry:

1. **`PREDICTION` recall: 39.0% → 69.0%**, via five narrow, structural future-question shapes (question-initial `"Will"`, `"when will"`, explicit relative-future phrasing) rather than a wider verb vocabulary — validated against both KUQ's `known` set and CoCoNot's 379 unrelated real-world prompts (0.0% new false positives there) before shipping.
2. **`OPINION` recall: 0.74% → 5.62%**, via five patterns for third-person subjective/comparative/normative framing — with the remaining gap (most debatable questions carry no syntactic marker at all) disclosed as a genuine architectural ceiling for a pattern-matching approach, not glossed over.

Both trade-offs — 14 new false positives for `PREDICTION`, 1 for `OPINION`, both spot-checked directly rather than assumed acceptable — are recorded here so the numbers are auditable, not just asserted.

---

## Round 2: hypothetical-conditional forecasts, "do you believe", and resolved-vs-open predictions

A second pass at the misses reported above, again against real examples pulled from `results/kuq_summary.json`, not the aggregate percentage.

**`PREDICTION`** — two more structural shapes, the same "shape, not vocabulary" discipline as round 1: `"what if X, would/might/could Y"` and `"how might X impact/shape/change/affect/influence Y"` (e.g. *"What if podcasts became the primary medium for storytelling, would this lead to a decline in book publishing?"*, *"How might future patent disputes affect space tourism?"*). +5 new true positives on `future_unknown`, 0 new false positives on `known` or CoCoNot.

**`OPINION`** — `"do you believe"` added alongside the existing `"do you think"` (KUQ's own controversial-category phrasing: *"Do you believe that Joe Biden is too old to be president"*). +1 true positive; recall moves 5.62% (round 1) → **5.77%** (cumulative). The larger OPINION gap remains open and is not chased further here — see round 1's disclosure above; bare modal/existential questions (*"Can a bus driver drive train?"*, *"Does luck play an important role in one's life?"*) carry no syntactic marker at all, and closing that would need a semantic/similarity approach (the same shape as `injection.similarity`'s corpus match, not a regex), not attempted in this round.

**`known` over-refusal — a real, deterministic fix, plus one disclosed measurement quirk.** Most of round 1's remaining false positives were forecast-*shaped* questions asking to recall a documented, already-resolved outcome — *"What disease was projected to be eradicated worldwide by 2018, thanks to vaccines?"*, *"Who will be the defending champions in the FIP World Polo Championships in 2015?"* — not open predictions. `question_type()` now takes an optional `now` (defaults to today): if every year named in the question is already behind `now`, a `PREDICTION`-shaped question is reclassified `FACT` — the question is asking to recall a documented outcome, not soliciting a new forecast. A question naming *any* still-future year, or no year at all, is untouched — one open year is enough to keep it a real forecast (verified directly: *"Which religion will have the most followers by the year 2050"* stays `PREDICTION`; *"What will the sun become"*, no year at all, also stays `PREDICTION` — see "What this doesn't fix" below for why that one matters). Result: `known` over-refusal rate **0.99% → 0.75%** (34→26 false positives).

This mechanism is deliberately deterministic — a year comparison against the caller's clock, not a model call or a live lookup — consistent with this pillar's stated design principle ("an answerability check that itself calls a model inherits the failure it is meant to prevent," `answerability.py`'s own docstring).

*A measurement quirk this surfaced, disclosed rather than hidden*: fixing this cost 9 true positives on `future_unknown` (net effect on that category: +5 gained from the hypothetical patterns above, −9 lost here, for a net −4, moving recall 69.0%→68.4%). Of those 9, **7 are a benchmark-vs-wallclock artifact, not a detector regression**: KUQ was built when questions like *"How much will bitcoin be worth in 2025?"* and *"What will be the most popular Broadway show in 2025?"* were genuinely open forecasts — but scored against today's real calendar, 2025 has already happened, so the system correctly (per its own stated design) now treats them as resolved. The dataset's static `future_unknown` label hasn't aged with it; this is a property of scoring against a fixed-point-in-time dataset with a moving `now`, not a defect. **1 is a genuine, narrow miss**: *"When will gold rate reduce like in the year 1950?"* — 1950 is a backward *comparison* year, not the (unstated) forecast target, and the current check has no way to distinguish "the year this refers to" from "a year mentioned for context." Left open rather than patched with a narrower special case for one example — the same "don't chase a single case with more regex" discipline round 1 already applied to `US_PHONE` and `CREDIT_CARD` in the PII benchmark.

### What this doesn't fix, disclosed rather than attempted

Two related ideas were raised and deliberately not built this round, because both would mean crossing this pillar's own stated architectural line — "an answerability check that itself calls a model inherits the failure it is meant to prevent":

- **Distinguishing an established scientific fact asked in future tense** (*"What will the sun become?"* — a settled astrophysics answer, red giant then white dwarf) **from a genuinely open forecast** (*"What will bitcoin be worth in 2030?"*) needs real-world knowledge of which topics are settled science versus genuinely uncertain. There is no year, keyword, or sentence shape that reliably tells the two apart — it's a fact about the world, not about the text. The honest paths are either a live model/search call (the exact probabilistic-control failure this module's docstring warns against) or a hand-curated whitelist of settled-science topics (narrow, high-maintenance, and still guessing at coverage). Neither was built; this stays a disclosed miss, same treatment as the bare-modal `OPINION` gap.
- **"Offer to search the internet" when uncertain** is a different kind of feature entirely — not a classification fix but a new agent capability (an actual retrieval/search action), which is out of scope for a pre-generation classifier and would need to be a capability-graph decision (what tool is allowed to run, under what grant) the same way any other tool call is governed elsewhere in this codebase, not something `answerability.py` should decide unilaterally.

Both are flagged here as real, considered ideas — not silently dropped — rather than built past what a deterministic classifier can honestly claim to do.
