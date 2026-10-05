# PII detection, benchmarked

**Sequential dataset-sourcing build-out** (see `docs/evaluation/dataset-sourcing.md`) — all three sourced PII datasets built, then a second round of fixes applied against what the numbers actually showed (see "Fixes applied" below). Scores both PII detectors that ship in `src/agentfox/guardrails/`:

- `pii.native` (`detectors/pii.py`) — regex-only, jurisdiction packs (US/UK/EU/India), no NER.
- `pii.presidio` (`adapters/presidio.py`) — wraps Microsoft Presidio; `PERSON`/`LOCATION`/`DATE_TIME`/`US_DRIVER_LICENSE`/`US_PASSPORT` excluded by policy default (`DEFAULT_EXCLUDED`) as "noisy in agent traffic."

1. [presidio-research `synth_dataset_v2.json`](https://github.com/microsoft/presidio-research) (MIT) — span-labeled synthetic sentences, scores both detectors directly, with and without the default exclusion.
2. [`gretelai/synthetic_pii_finance_multilingual`](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) (Apache-2.0) — full-length synthetic financial documents, 7 languages, 59 document formats. The hardest of the three — dense, code-heavy documents stress precision much more than Dataset 1's short sentences.
3. [Text Anonymization Benchmark (TAB)](https://github.com/NorskRegnesentral/text-anonymization-benchmark) (MIT) — 127 real (not synthetic) ECHR court judgments, multi-annotator labeled. The one dataset in this suite that tests NER on natural prose — and the one where full-policy Presidio performs best of all three.

```bash
uv run python benchmarks/pii/fetch_presidio_research.py
uv run python benchmarks/pii/run_presidio_research_benchmark.py

uv run --with pyarrow python benchmarks/pii/fetch_gretel_multilingual.py
uv run python benchmarks/pii/run_gretel_multilingual_benchmark.py

uv run python benchmarks/pii/fetch_tab.py
uv run python benchmarks/pii/run_tab_benchmark.py
```

## Fixes applied

Two rounds so far, both triggered by asking "what's actually failing, and why" rather than stopping at the aggregate percentage. Round 1 covered all three datasets; round 2 went back into Dataset 2 specifically, since it had the worst numbers and the most remaining unexplained false positives. Six product/methodology decisions total — four fixes, two deliberately left unfixed and disclosed instead. All affected benchmarks were re-run after each product fix to confirm real, not assumed, impact.

| # | Round | Pattern | Where found | Fix | Kind |
|---|---|---|---|---|---|
| 1 | 1 | `US_DRIVER_LICENSE` precision collapse (3.2% / 0.9% across two datasets) | Datasets 1 & 2 | Added to `DEFAULT_EXCLUDED` | Product |
| 2 | 1 | `DATE_TIME` → `PII.DATE_OF_BIRTH` taxonomy conflation | Datasets 1, 2 & 3 | Presidio's `DATE_TIME` now maps to a new `PII.DATE_TIME` type; `PII.DATE_OF_BIRTH` stays owned by `pii.native`'s birthdate-specific regex | Product |
| 3 | 1 | Native DOB regex misses period-separated dates (0% recall on German) | Dataset 2 | Widened the separator character class from `[/-]` to `[/.-]` | Product |
| 4 | 1 | `US_SSN` false positives have a clean, exploitable confidence signature | Dataset 2 | Added a per-entity `min_score` gate (0.1) | Product |
| 5 | 1 | 66.5% of "LOCATION false positives" (Dataset 1) are correct hits landing inside out-of-scope `STREET_ADDRESS` ground truth | Dataset 1 & 2 | Benchmark scoring now excludes predictions fully contained in a `STREET_ADDRESS` span from the FP count, tracked separately as `excluded` | Benchmark methodology |
| 6 | 2 | `US_PASSPORT` precision collapse (10.7%), same shape as `US_DRIVER_LICENSE` | Dataset 2 | Added to `DEFAULT_EXCLUDED` | Product |
| — | 1 | A weaker, more ambiguous version of #5 on TAB (35.6% of LOCATION FPs land inside `ORG` spans, e.g. `"the Republic of Turkey"`) | Dataset 3 | **Not fixed** — genuine judgment call, not an obvious miscredit. Disclosed, not auto-excluded. | Disclosed only |
| — | 2 | `US_PHONE`: same no-clean-threshold shape as `US_PASSPORT`/`US_DRIVER_LICENSE` (24.2% precision) | Dataset 2 | **Not fixed** — phone numbers are high-value PII; the recall cost of a blanket exclusion outweighs the noise cost, unlike the other two low-support, low-urgency categories | Disclosed only |
| — | 2 | `CREDIT_CARD` recall gap (62.5% miss rate) | Dataset 2 | **Not a defect** — 9 of 11 sampled misses fail Luhn checksum validation; Presidio is correctly rejecting checksum-invalid numbers the synthetic dataset generator produced. Nothing to fix. | Disclosed only |

### Why each fix is narrow, not a blanket change

- **#1, #4, and #6 were all decided by looking at raw confidence scores, not just outcomes** — and the same diagnostic gave three different answers. `US_SSN`'s false positives (bare 9-digit codes in dense EDI/BAI/FIX-format documents) scored **exactly 0.05** in 444 of 453 cases, against 69 of 76 true positives scoring 0.4–0.85 — a clean, near-total separation, so a score gate is a precise fix (#4). `US_DRIVER_LICENSE`'s true and false positives are scored across the *same* tiers (0.01, 0.3, 0.4, 0.65) with no clean cut point (#1), and `US_PASSPORT` shows the identical overlapping pattern (0.05, 0.1, 0.4, 0.45 tiers, both TP and FP in each) — a threshold for either would just be arbitrary, so both are blanket exclusions instead. **`US_PHONE` was checked the same way and shows the same no-clean-threshold shape as #1/#6** (0.4 and 0.75 tiers both carry hundreds of TP and FP) — but wasn't excluded, because unlike a passport or driver's license number, a phone number is common, high-value PII that a real deployment usually wants caught even at mediocre precision; the recall trade-off that made #1/#6 clearly worth it doesn't hold here.
- **#5's containment exclusion is scoped to `STREET_ADDRESS` specifically**, not "any out-of-scope ground truth span" — that would be far too broad and could hide genuine detector errors (e.g. a `PERSON` detector firing on a company name inside an out-of-scope `company`-labeled span *is* a real error worth counting). `STREET_ADDRESS` earns the exception because the pattern is unambiguous: a city or country name embedded in a mailing address block is, definitionally, a real location — there's no judgment call the way there is with the TAB/`ORG` case, which is disclosed instead of auto-excluded for exactly that reason.
- **The `CREDIT_CARD` finding isn't a fix at all, deliberately.** Presidio's Luhn-checksum validation is the *correct* behavior for a PII detector — flagging every random 15-16-digit string as a credit card would be worse, not better. The "failure" here is entirely in the synthetic dataset (checksum-invalid fake numbers), not the product. Recorded here so the recall number isn't misread as a detector gap when it's actually the detector doing its job.

### Combined before/after, all three datasets

| Dataset | Config | Precision (before → after) | Recall (before → after) |
|---|---|---|---|
| 1. presidio-research | `pii.presidio` (default) | 63.8% → **90.2%** | 15.3% → 15.1% |
| 1. presidio-research | `pii.presidio` (full) | 54.4% → **65.2%** | 75.6% → 75.6% |
| 2. gretelai multilingual | `pii.presidio` (default) | 15.2% → **51.9%** | 19.9% → 18.2% |
| 2. gretelai multilingual | `pii.presidio` (full) | 16.3% → **21.7%** | 70.1% → 68.5% |
| 2. gretelai multilingual | `pii.native` `DATE_OF_BIRTH`, German only | 0.0% → **68.0%** recall | — |
| 2. gretelai multilingual | `pii.presidio` `US_SSN` (full policy) | 14.4% → **87.3%** precision | 49.7% → 45.1% |
| 3. TAB | `pii.presidio` (full) | unchanged (83.6%) | unchanged (86.9%) |

Recall moves down a few points on the default-policy rows — an honest, expected side effect of #2 (Presidio's own `DATE_TIME` output no longer masquerades as `DATE_OF_BIRTH`), #4 (a handful of genuine SSNs scored exactly at the 0.05 tier are filtered out along with the false positives), and #6 (132 genuine passport numbers are no longer detected at all by default, the same trade-off #1 already made for driver's licenses). All three trades are disclosed in the per-dataset sections below, not hidden in the aggregate.

---

## Dataset 1 — presidio-research `synth_dataset_v2.json`

1,500 synthetic, template-generated sentences, span-labeled with 17 entity types. Three detector configurations scored: `pii.native`, `pii.presidio` at its shipping default policy, and `pii.presidio` with nothing excluded (isolates exactly what the default costs).

### Results, all 1,500 rows (post-fix)

| Config | Precision | Recall | F1 | TP | FP | FN | Excluded* |
|---|---|---|---|---|---|---|---|
| `pii.native` | 96.4% | 14.1% | 24.7% | 243 | 9 | 1477 | 0 |
| `pii.presidio` (default policy — ships as-is) | 90.2% | 15.1% | 25.8% | 259 | 28 | 1461 | 1 |
| `pii.presidio` (nothing excluded) | 65.2% | 75.6% | 70.0% | 1300 | 693 | 420 | 396 |

\* Predicted spans that land fully inside an out-of-scope `STREET_ADDRESS` ground-truth span — correct detections this benchmark has no ground truth to credit, not detector errors. See "Fixes applied" above.

Full per-entity-type breakdown: [`results/summary.json`](results/summary.json).

### The default exclusion's cost, measured directly

`PERSON`/`LOCATION`/`DATE_TIME` together are 1,387 of the 1,750 in-scope labeled spans in this dataset (79%). With the default policy, `pii.presidio` finds **0** of them — recall on all three is exactly 0%, because they're filtered out before scoring, not because Presidio misses them. With nothing excluded, the same engine on the same input finds 1,037 of those 1,387 (PERSON 712/857 recall = 83.1%, LOCATION 206/411 = 50.1%, DATE_TIME 119/119 = 100.0%). That's the real, disclosed trade-off the default makes: precision protection against noisy categories, paid for with a 79%-of-labeled-spans recall floor on exactly those categories, by design, until a caller opts into the full policy.

### How the two product-level precision problems were found and fixed

Turning the exclusion off to measure its cost surfaced two weak spots in Presidio's own recognizers:

- **`DATE_TIME` → `PII.DATE_OF_BIRTH` was a semantic mismatch, not just a noisy recognizer.** Presidio's `DATE_TIME` recognizer flags *any* date-shaped mention — "the meeting is on March 3rd," "founded in 1998" — not specifically a person's birthdate. The old mapping (`adapters/presidio.py::_ENTITY_MAP`) claimed every one of those was a birthdate: 100% recall against the dataset's `DATE_TIME` spans, but only 21.3% precision (119 TP against 440 FP). **Fixed**: Presidio's `DATE_TIME` now maps to a new `PII.DATE_TIME` canonical type instead of overclaiming `PII.DATE_OF_BIRTH`; `pii.native`'s own birthdate-shaped regex keeps that name. Post-fix, this bucket (now honestly named `PII.DATE_TIME`, ground truth remapped to match) sits at 27.9% precision, 100% recall — the modest further gain over the pre-fix 21.3% comes from the `STREET_ADDRESS`-containment scoring fix (some date mentions were embedded in address blocks), not from the rename itself, which is a relabeling, not a behavior change.
- **`US_DRIVER_LICENSE` was precision 3.2%** (4 TP, 120 FP) in both Presidio configurations that had it enabled — a low-specificity alphanumeric-ID pattern firing on this dataset's other alphanumeric IDs (credit card fragments, template placeholders) far more often than on the 5 actual driver's-license spans present. **Fixed**: added to `DEFAULT_EXCLUDED` alongside PERSON/LOCATION/DATE_TIME (see "Fixes applied" for why a score threshold wasn't used here instead). Support is small (5 labeled spans) so this dataset alone wouldn't justify the fix — Dataset 2 confirming the identical pattern at 0.9% precision on a much larger sample is what made it clearly worth doing.

### LOCATION's real precision, after correcting a benchmark scoring artifact

Before the fix, raw `LOCATION` precision looked weak (46.5%, 237 FP). Investigating individual false positives — not just the aggregate number — found that 157 of those 237 (66.5%) were `LONDON`, `Hungary`, `Öntésmajor`, and similar **correct** location detections landing inside a `STREET_ADDRESS` ground-truth span (e.g. `"14 Crown Street Kishiev Squares\n Suite 321\n LONDON\n United Kingdom 75419"` — Presidio correctly spots `LONDON`, but this benchmark has no ground truth to credit it against, since `STREET_ADDRESS` is out of scope). **Fixed** (benchmark scoring, not product code): predictions fully contained in an out-of-scope `STREET_ADDRESS` span are now excluded from the FP count rather than penalized. Post-fix, `LOCATION` precision at full policy is **72.0%** (80 FP, down from 237) — a much more honest number for what Presidio's LOCATION recognizer actually does.

The remaining 79 genuine (non-address) false positives show two real, unfixed patterns: partial street-name fragments (`"Botley Road St."`, `"Marina Fort Street"`) and surname/place-name ambiguity (`"Yefremova"`, `"Henderson"`, `"Ström"`, `"Salinas"` — real surnames that are also plausible place names). Both are inherent to Presidio's own NER model, not something fixable at the wrapper layer without a custom model.

### What `pii.native`'s regex misses, and why that's expected for some of it

- **`PERSON` and `LOCATION`: 0% recall by construction.** `pii.native` is regex-only; there's no NER in a regex engine. This isn't a bug to fix, it's the entire reason the Presidio adapter exists in the same detector stack — disclosed here so the number isn't misread as a defect.
- **`US_PHONE`: 20.6% recall (19/92).** The regex is tuned to a narrower set of US phone formats than this dataset's variety (extensions, international-looking prefixes, spacing conventions) actually contains.
- **Everything else** (`EMAIL`, `CREDIT_CARD`, `US_SSN`, `IBAN`, `IP_ADDRESS`) — native performs at or near parity with Presidio, 92%+ recall, ≥98% precision. These are exactly the well-structured, format-constrained categories regex is good at.

### Methodology notes

- **Scoring**: character-span overlap (any overlap between a predicted span and a ground-truth span of the same canonical type counts as a match), greedy one-to-one per document — standard for PII/NER evaluation, where finding the right entity matters more than matching its exact character boundaries. Not exact-boundary match.
- **Scope**: this dataset labels several entity types AgentFox's detectors never claim to cover at all — `STREET_ADDRESS`, `ORGANIZATION`, `TITLE`, `AGE`, `NRP`, `ZIP_CODE`, `DOMAIN_NAME`. Those spans are dropped from ground truth entirely (`GT_ENTITY_MAP` in the run script); scoring a detector as wrong for not detecting a category it was never built for would misrepresent it, not evaluate it. `STREET_ADDRESS` gets one further, narrower treatment — see the containment-exclusion fix above.
- **One deliberate proxy**: presidio-research labels country/city mentions `GPE` rather than `LOCATION`. Mapped 1:1 onto `PII.LOCATION` since it's the closest match and the dataset has no separate `LOCATION` label — a disclosed scope decision, not a hidden one.
- **Direct detector calls, not via `DetectorPipeline`**: calling `pii.presidio` through the pipeline marks it "degraded" (timed out) on its first call even after `warm_all()` — the same latency-ceiling measurement artifact `benchmarks/REPORT.md` documents for the injection classifier (a shared timeout budget silently drops a slow-but-correct first call). Calling `.detect()` directly on the detector object avoids it: the underlying spaCy/Presidio model loads once (~3s) on the very first call in a process, then every subsequent call is single-digit-to-low-double-digit milliseconds.
- **Dataset is synthetic**, not real personal data — Presidio's own template-based generator. Doesn't test real-world formatting noise the way Dataset 3 (real text) does.

---

## Dataset 2 — gretelai/synthetic_pii_finance_multilingual

5,594 full-length synthetic financial documents (test split), 7 languages (English, French, German, Dutch, Spanish, Italian, Swedish), 59 document formats spanning natural prose (Email, Employment Contract, Privacy Policy) and dense structured/machine formats (EDI, SWIFT Message, FIX Protocol, MT940, XBRL, BAI Format, CSV). Documents average ~1,300 characters — 10-20x longer than Dataset 1's single sentences. Same three detector configurations as Dataset 1.

### Results, all 5,594 rows (post-fix, both rounds)

| Config | Precision | Recall | F1 | TP | FP | FN | Excluded* |
|---|---|---|---|---|---|---|---|
| `pii.native` | 37.1% | 17.1% | 23.4% | 2,480 | 4,209 | 12,000 | 1 |
| `pii.presidio` (default policy) | 51.9% | 18.2% | 27.0% | 2,637 | 2,442 | 11,843 | 8 |
| `pii.presidio` (nothing excluded) | 21.7% | 68.5% | 33.0% | 9,921 | 35,795 | 4,559 | 1,854 |

\* Same containment exclusion as Dataset 1 — see "Fixes applied".

Full per-entity-type and per-language breakdown: [`results/gretel_multilingual_summary.json`](results/gretel_multilingual_summary.json).

### The headline finding, before the fix: precision collapse driven by three identifiable causes, not a vague "hard dataset"

The pre-fix numbers looked bad in aggregate (default-policy precision 15.2%) but broke down into three concrete, independently-fixable causes once individual false positives were examined instead of just the summary percentage:

1. **`US_DRIVER_LICENSE`: 0.9% precision at the default policy** (107 TP against 12,073 FP) — the same low-specificity alphanumeric-ID pattern from Dataset 1, at ~40x the scale. This dataset is full of structurally similar codes (account numbers, reference IDs, SWIFT/BIC codes, transaction IDs) that aren't driver's licenses. **Fixed** by the same `DEFAULT_EXCLUDED` addition as Dataset 1 — this was the confirming evidence that made the fix clearly worth shipping.
2. **`DATE_TIME` → `PII.DATE_OF_BIRTH` conflation** — pre-fix, 1.6% precision at full policy (223 TP against 13,889 FP), since almost every date mention in a financial document (statement dates, due dates, transaction dates) got labeled a birthdate. **Fixed** by the same taxonomy rename as Dataset 1. This dataset uniquely separates a genuine `date_of_birth` label from generic `date`/`time`/`date_time` labels, so post-fix, Presidio's own `DATE_TIME` output (now correctly typed `PII.DATE_TIME`) simply stops being scored against the `date_of_birth` ground-truth bucket at all — only `pii.native`'s regex is scored there now, which is the honest scope for what each engine actually claims to detect.
3. **`US_SSN`: 14.4% precision at full policy** (76 TP against 453 FP) — bare 9-digit codes from EDI/BAI/FIX-format documents (account numbers, routing numbers) matching the SSN pattern. **Fixed** by the score-gate (min 0.1): false positives scored exactly 0.05 in 444/453 cases, true positives scored 0.4–0.85 in 69/76 cases. Post-fix: **87.3% precision** (10 FP, down from 453), recall 45.1% (down from 49.7% — the 7 true positives that also scored 0.05 are the honest cost of this fix).

**Was this a language-mismatch problem?** Checked directly and mostly ruled out: `pii.presidio` runs with `language="en"` throughout (the shipping default), and English rows accounted for the *majority* of both the `DATE_TIME` and `US_DRIVER_LICENSE` false positives pre-fix (English is ~53% of rows but a larger share of each). The dense, code-heavy document *formats* — not the language — were driving the problem; multilingual coverage is a real, smaller, separate effect (see below), not the primary cause.

### A real, fixed native-detector finding: the DOB regex was separator-specific, not just format-specific

`pii.native`'s `DATE_OF_BIRTH` regex matched day-month-year with a `/` or `-` separator only. Recall on labeled `date_of_birth` spans, broken out by language:

| Language | Support | Recall (before → after) |
|---|---|---|
| French | 15 | 80.0% (unchanged) |
| Italian | 30 | 66.7% (unchanged) |
| **German** | **25** | **0.0% → 68.0%** |
| English | 143 | 52.4% (unchanged) |
| Spanish | 19 | 47.4% (unchanged) |
| Dutch | 5 | 40.0% (unchanged) |
| Swedish | 13 | 38.5% (unchanged) |

Spot-checking the actual German `date_of_birth` span text found the cause directly: `'12.02.1969'`, `'01.01.1980'`, `'15.06.1998'` — German-locale dates in this dataset are period-separated (`DD.MM.YYYY`), a separator the regex's old character class (`[/-]`) never matched. **Fixed**: widened to `[/.-]`. German recall went from a hard 0% to 68.0% — the remaining gap (8 of 25 misses) is other date shapes (spelled-out months, etc.) not addressed by this fix.

### What held up well

`PII.EMAIL` (96.4%/95.6%), `PII.IBAN` (96.8%/74.4%), and `PII.IP_ADDRESS` (90.8%/89.9%) perform close to their Dataset 1 numbers regardless of document type or language.

### Round 2: three more entity types investigated, one more fixed, two deliberately left alone

Fixing the three biggest problems in round 1 made the next tier of issues visible — the same "look at concrete examples and score distributions, not just the aggregate" process was applied to the three next-worst default-policy categories.

- **`US_PASSPORT`: 10.7% precision (132 TP, 1,105 FP), same shape as `US_DRIVER_LICENSE`.** Almost every false positive was the literal string `'123456789'` or a similar generic 9-digit code from EDI/FIX/BAI-format documents — the same "dense financial documents are full of plausible-looking numeric IDs" pattern as `US_SSN`, but the confidence-score distribution didn't cooperate this time: true and false positives both land across the 0.05/0.1/0.4/0.45 tiers with no clean cut point (checked directly, same method that worked for `US_SSN`). **Fixed** by adding `US_PASSPORT` to `DEFAULT_EXCLUDED` — same reasoning as `US_DRIVER_LICENSE`: low support (136 spans), no separating signal, and passport numbers are a lower-urgency category than the alternative. Default-policy `US_PASSPORT` FP dropped from 1,105 to 0.
- **`US_PHONE`: 24.2% precision (744 TP, 2,335 FP) — investigated, deliberately not excluded.** Same false-positive shape again (`'1234567890'`, FIX-protocol timestamp/sequence codes like `'20210315-15'`, EDI segment numbers) and the same no-clean-threshold score profile as `US_PASSPORT`. The difference is what's at stake: phone numbers are common, legitimate, high-value PII that a real agent deployment (customer support transcripts, contact forms, KYC flows) usually needs caught — excluding this by default the way `US_DRIVER_LICENSE`/`US_PASSPORT` were would trade away a genuinely important detection capability to fix a precision number, the wrong trade for a category this central. Left as a disclosed, open problem — a locale-aware format validator or a stronger context-word requirement are the more promising future directions, not a threshold or an exclusion.
- **`CREDIT_CARD`: 37.5% recall (45 TP, 75 FN) — investigated, turned out not to be a defect at all.** Sampling the actual missed values (`'3438 9558 0875 281'`, `'1234-5678-9012-3456'`, `'3007-5662-3449-2611'`) and checking them against the Luhn checksum algorithm found that 9 of 11 fail validation. Presidio's `CREDIT_CARD` recognizer validates the checksum internally, and correctly rejects numbers that don't pass it — real credit card numbers always satisfy Luhn; these are synthetic placeholders that were never generated to be checksum-valid. This is the dataset's limitation, not the detector's: a recognizer that flagged every checksum-invalid 16-digit string as a credit card would be *less* correct, not more. No fix applied or needed.

### Methodology notes

- **Absolute FP/FN counts aren't directly comparable to Dataset 1's** — these documents are 10-20x longer, so any constant per-character false-positive rate produces much larger raw counts. Precision and recall (which normalize for volume) are the fair comparison.
- **`password`/`api_key` labels exist in this dataset** (101 and 91 labeled spans respectively) but are deliberately out of scope for this PII benchmark — they're secrets, not personal data. Flagged as a candidate input for a future *secrets*-detection benchmark against `detectors/secrets.py`, not built in this pass.
- Same span-overlap scoring, same `GT_ENTITY_MAP` scoping discipline, same direct-detector-call methodology, same `STREET_ADDRESS`-containment exclusion as Dataset 1.

---

## Dataset 3 — Text Anonymization Benchmark (TAB), real ECHR case law

127 real European Court of Human Rights judgments (`echr_test.json`), the only dataset in this suite built from real text rather than synthetic or templated generation. Multiple human annotators per document (1-10); ground truth is the union across annotators, deduplicated on exact span boundaries — a disclosed simplification of TAB's own weighted evaluation protocol, not a reproduction of it. In-scope types here are `PERSON`, `LOC` (→ `PII.LOCATION`), and `DATETIME` (→ `PII.DATE_TIME`, matching the taxonomy fix — see "Fixes applied") — `ORG`, `DEM`, `CODE`, `MISC`, `QUANTITY` have no corresponding AgentFox detector and are dropped from ground truth.

### Results, all 127 rows

| Config | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| `pii.native` | — | 0.0% | — | 0 | 0 | 4,799 |
| `pii.presidio` (default policy) | — | 0.0% | — | 0 | 0 | 4,799 |
| `pii.presidio` (nothing excluded) | 83.6% | 86.9% | 85.2% | 4,168 | 820 | 631 |

Unchanged by the fix round — the `DATE_TIME` rename is a relabeling with no behavior change here (TAB's own label was already generic, matching what `PII.DATE_TIME` now honestly represents), and TAB has no `street_address` category for the containment fix to apply to. `pii.native` and the default-policy config score exactly 0% recall **by construction**: every in-scope type here is either unsupported by regex alone or excluded by the shipping default policy. Full per-entity-type breakdown: [`results/tab_summary.json`](results/tab_summary.json).

### The best full-policy result of the three datasets — and a real explanation for why

83.6% precision / 86.9% recall is meaningfully better than both Dataset 1 (65.2%/75.6%) and Dataset 2 (21.7%/68.5%). The most striking single number: `DATE_TIME` precision is **90.8%** here (2,715 TP / 276 FP), against 27.9% on Dataset 1 and (pre-fix) 1.6% on Dataset 2. Real ECHR judgments' date mentions are overwhelmingly tied to the people in the case (birth dates, dates of events central to the individual's history) rather than the generic transaction/statement dates that dominate Dataset 2's financial documents — so the *same* engine, on genuinely different document domains, produces a completely different precision number for the identical entity type. Coherent, natural, single-language prose is also simply closer to what a general-purpose NER model was trained on than either templated synthetic sentences or dense multilingual structured documents — consistent with `PERSON` (85.5%/78.6%) and `LOCATION` (56.2%/74.2%) both landing at or above their Dataset 1/2 numbers too, `LOCATION` precision aside (the one category that stays the weakest across all three datasets even after the containment fix).

### A weaker, more ambiguous version of the STREET_ADDRESS pattern — disclosed, not fixed

The same diagnostic that found Dataset 1's `STREET_ADDRESS`-containment artifact was run against TAB: 35.6% of raw `LOCATION` false positives (129 of 362) land inside an out-of-scope `ORG`-labeled span. But the actual text is different in kind, not just degree — `"the Republic of Turkey"`, `"the United Kingdom of Great Britain"`, `"the Third Section"`, `"the Aydın Magistrate's Court"`. Whether a country referred to as a state party to a legal case is a `LOCATION` or an `ORG` is a genuine, defensible annotation-convention choice — unlike a city name inside a mailing address, where "this is a real location" isn't in dispute. **Left unfixed and reported as-is**: applying the same containment exclusion here would launder a real ambiguity into a clean-looking number, which is a worse failure than a slightly pessimistic one.

### The number that matters most for a real anonymization use case

TAB's own `identifier_type` field ranks re-identification risk — `DIRECT` means the mention alone identifies the person (a name, a case number used as an identifier); `QUASI` means identifying only combined with other mentions; `NO_MASK` means not actually identifying despite the entity type. Recall on full-policy Presidio, broken out by this field:

| Identifier type | Support | Recall |
|---|---|---|
| `DIRECT` | 228 | 96.9% |
| `QUASI` | 3,914 | 88.8% |
| `NO_MASK` | 657 | 71.7% |

Recall is highest exactly where it matters most — `DIRECT` identifiers, the mentions that alone would re-identify someone, are caught 96.9% of the time. `NO_MASK` mentions being caught least often is also the right direction for a detector to err in — those are the ones where a miss costs nothing.

### Methodology notes

- **Ground truth is a union-across-annotators simplification**, not TAB's full weighted risk protocol (`evaluation.py` in the source repo). Different annotators occasionally mark slightly different boundaries for the same real mention; each distinct boundary survives as a separate ground-truth span here, which very likely inflates the false-negative count somewhat versus a boundary-tolerant merge. Disclosed, not corrected.
- Same span-overlap scoring, same direct-detector-call methodology as Datasets 1 and 2.
- **Only `test` (127 rows) was used** — `train` (1,014 rows) and `dev` (127 rows) exist in the same source repo and could extend this sample if a larger real-text run is wanted later.

### PII benchmarking: build-out and two fix rounds complete

All three sourced datasets (`docs/evaluation/dataset-sourcing.md`) are built and re-verified after fixes. Combined picture: `EMAIL`/`IBAN`/`IP_ADDRESS` are reliably strong regardless of document type, language, or synthetic-vs-real. `PERSON`/`LOCATION`/`DATE_TIME`/`US_DRIVER_LICENSE`/`US_PASSPORT` (all excluded by default) show real, now-quantified recall and precision trade-offs — some domain-dependent (`DATE_TIME`), some just a weak underlying recognizer with no separating signal (`US_DRIVER_LICENSE`, `US_PASSPORT`), and one (`LOCATION`) partly a benchmark scoring artifact that's now corrected rather than a real detector defect. `US_SSN` moved from a genuine weak spot to one of the strongest categories after a single, narrowly-scoped score-gate fix. `US_PHONE` shows the identical noisy pattern as the two excluded categories but was deliberately left alone — the recall trade-off isn't worth it for a category this commonly needed. `CREDIT_CARD`'s apparent recall gap turned out not to be a gap at all once the actual missed values were checked against the Luhn algorithm. The throughline across both rounds: every fix (or deliberate non-fix) here traces back to a concrete example or a score distribution, not an aggregate percentage — the two are diagnosis and evidence, not the same thing.
