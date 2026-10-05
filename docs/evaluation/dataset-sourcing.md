# Dataset sourcing — the next round of benchmarks

**Internal planning document, not a benchmark report.** This is the research that precedes actually building `benchmarks/`-style harnesses for the capabilities beyond prompt-injection detection. It follows the same discipline as [`benchmarks/data_generalization/README.md`](../../benchmarks/data_generalization/README.md): every dataset is named, its license verified directly (not inferred from a badge — several candidates below looked clean until the actual `LICENSE` file was fetched), and rejected candidates are recorded with reasons so they aren't re-litigated next time this list is revisited. Discipline: **MIT / Apache-2.0 / CC-BY-permissive only.** CC-BY-NC, CC-BY-SA, ODC-BY, no-license, and "MIT plus a restrictive field-of-use clause" are all treated as unusable, consistent with the exclusions already documented for the injection-detection generalization set (TensorTrust, BIPIA, wildjailbreak, BeaverTails).

Five capability areas researched in parallel, each required to surface at least three independently-sourced candidates. All five came back with real, usable options — and, just as valuable, real gaps: several failure modes have **no** public dataset that matches AgentFox's specific mechanics, and would need a synthetic layer built on top of a real corpus rather than a drop-in benchmark. That's recorded per section below, not glossed over.

---

## F3 — Destructive-action & blast-radius analysis

Detection lives in `src/agentfox/guardrails/actions.py` (deterministic sqlglot SQL parsing, a shell deny-list, HTTP/scope checkers, environment binding).

| Dataset | License | Size | Fit |
|---|---|---|---|
| [`gretelai/synthetic_text_to_sql`](https://huggingface.co/datasets/gretelai/synthetic_text_to_sql) | Apache-2.0 | 105,851 rows, 100 domains, `CREATE TABLE` context included | Benign seed corpus — strip `WHERE` clauses or inject tautologies to generate F3.1/F3.3 positives; `DROP TABLE`/DDL rows seed F3.2 |
| [ToolEmu](https://github.com/ryoungj/ToolEmu) | Apache-2.0 | 144 hand-authored cases, 38 toolkits | 30 `Terminal`-toolkit cases map to `analyse_shell`; general F3.6/F3.9 irreversibility scenarios |
| [`payload-box/sql-injection-payload-list`](https://github.com/payload-box/sql-injection-payload-list) | MIT | Hundreds of fragments, per-dialect | Raw evasion shapes for `analyse_scope`'s SQLi-fragment regex and F3.5 comment/stacked-statement testing |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | MIT | 97 user tasks + 629 injection cases, 4 suites | Pre/post-environment diffing — direct fit for F3.6 (unverified-state) and constructible F3.7 (duplicate-on-retry) tests |
| **[InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent)** | MIT | 1,054 cases, 17 user tools, 62 attacker tools | **Direct match for F3.8** — the one F3 mode `failure-modes.md` marks genuinely absent (composed privilege escalation). Structurally separates a read-tool response (data-flow source) from a privileged write/auth call (sink) in a labeled, reusable way — nothing else found does this |

**Rejected:** a Kaggle SQLi CSV (license unverifiable — JS-rendered page, no confirmable tag), **AgentHarm** (MIT *plus* a restrictive field-of-use clause — not clean MIT despite the label), Spider (CC-BY-SA, also read-only/no destructive examples), R-Judge (CC-BY-NC-SA).

**Gap:** nothing carries a declared `production`/`staging` environment label — F3.4 ("wrong environment," the actual 1.9M-row incident) needs that synthesized on top of one of the above, not sourced as-is.

---

## F4 — Entitlement & disclosure control

Detection lives in `src/agentfox/entitlement.py` (default-deny ACL filtering, restricted-class tiers, purpose limitation, k-anonymity aggregation checks, inference-risk detection) and `src/agentfox/tenancy.py` (session-level isolation — not benchmarkable against a public dataset, it's an integration-test target).

| Dataset | License | Size | Fit |
|---|---|---|---|
| [ConfAIde](https://github.com/skywalker023/confaide) | MIT | 4 tiers, up to ~2,000 items each | Contextual-integrity judgment — best fit for F4.5 (inference disclosure) and F4.6 (purpose limitation) |
| [PrivacyLens](https://github.com/SALT-NLP/PrivacyLens) | MIT | 493 entries, real tool trajectories | Agent action logs (retrieve from A, about to disclose in B) — best fit for F4.1 and F4.6 |
| [AgentLeak](https://github.com/Privatris/AgentLeak) | MIT (verified from file content; GitHub's auto-detector misflags it — re-check before compliance sign-off) | 1,000 scenarios, 4 verticals | Allow/forbid field schema near-identical to `entitlement.py`'s own model; per-agent `clearance` field maps to F4.2; scoring across 7 leakage channels |

**Rejected:** **TOP-R** and **SPILLage** — both are near-perfect structural matches for F4.4 (aggregation disclosure) and F4.1 respectively, but neither repo has a LICENSE file at all. Worth periodically re-checking. Also rejected: a "Permission-Aware RAG" methodology paper with no released dataset (builds on CC-BY-SA HotpotQA anyway), ToolPrivacyBench (described in its paper, never released), generic document-classification sets (wrong label type — document type, not sensitivity), and the Enron corpus (inconsistent licensing across mirrors, not worth the provenance chase without a specific need).

**Gap, stated plainly:** no dataset found matches the literal shape `NativeAclEngine.visible()` needs — a fixed document corpus with per-document grants, principal identities, and retrieval-filtering ground truth. This looks like a genuine hole in the public benchmark landscape, not a search failure. Best path: adapt TOP-R's scenario-construction *methodology* (or PrivacyLens's trajectory format) over a permissively-licensed corpus, rather than waiting for the ideal dataset to appear.

---

## PII & secrets detection

Detection: `src/agentfox/guardrails/detectors/pii.py` (native regex) + Presidio adapter (`PERSON`/`LOCATION`/`DATE_TIME` excluded by default as "noisy"), and `src/agentfox/guardrails/detectors/secrets.py` (named formats + entropy-gated generic fallback).

| Dataset | Capability | License | Size | Fit |
|---|---|---|---|---|
| [presidio-research `synth_dataset_v2.json`](https://github.com/microsoft/presidio-research) | PII (synthetic) | MIT | 1,500 rows, span-labeled | Entity taxonomy maps ~1:1 onto the Presidio adapter; `PERSON` is 37% of all labeled spans — the cleanest way to put a real number on what the default `PERSON`/`LOCATION` exclusion actually costs in recall |
| [`gretelai/synthetic_pii_finance_multilingual`](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) | PII (synthetic, multilingual) | Apache-2.0 | 55,940 rows, 6 languages | Tests locale coverage — the `DATE_OF_BIRTH` regex is DD/MM/YYYY-only and will likely miss non-US date formats in the FR/DE/NL/ES/IT rows. Also carries `password`/`api_key` labels, doubling as a secrets test |
| [Text Anonymization Benchmark (TAB)](https://github.com/NorskRegnesentral/text-anonymization-benchmark) | PII (real text) | MIT | 1,268 real ECHR court cases | Real prose, not templated — the only real stress test found for Presidio's `PERSON`/`ORGANIZATION` NER on natural legal text; `DIRECT`/`QUASI` labels separate "found a person" from "found the right kind of identifying mention" |
| [Samsung CredData](https://github.com/Samsung/CredData) | Secrets | Apache-2.0 harness, **mixed per-file provenance** ⚠ | 4,583 true / 73,842 candidate lines from 297 real GitHub repos | Real-world credential variety beyond our ~10 named formats. Flagged, not rejected: content is pulled from real repos each under their own (verified-permissive-at-curation-time, but not individually re-verifiable at this scale) license — needs a human license call before use |
| [SecretBench](https://github.com/setu1421/SecretBench) | Secrets | MIT | 15,084 true / 97,479 candidates | Rich per-secret metadata (`entropy`, `is_template`) close to purpose-built for validating an entropy-threshold design. **Access-gated**: requires contacting the authors and signing a data agreement — MIT-licensed but not a same-day download |

**Rejected:** the entire `ai4privacy` dataset family (a custom tiered/BSL-shaped license — free only ≤3-person entities, paid corporate license above that; one variant has no license file at all) and Yelp's `detect-secrets` test fixtures (clean Apache-2.0, but only a few dozen secrets — not benchmark-grade).

---

## F1 — Answerability & abstention

Detection: `src/agentfox/answerability.py` — a **declared-boundary** system (systems of record, coverage window, entity roster, answerable question types), not a generic unanswerable-question classifier.

**Important correction surfaced by this research:** the whitepaper cites AbstentionBench (arXiv:2506.09038) as the field's primary academic benchmark for this area. **AbstentionBench itself is CC-BY-NC-4.0** — verified directly against its HF card and repo LICENSE file — which fails this project's own license bar. It's cited in the whitepaper only as a research finding ("reasoning fine-tuning degrades abstention"), not as something benchmarked against, so no correction is needed there. But it rules the packaged dataset out for actual use. Several of its 20 constituent datasets, however, carry independent, permissive licenses and can be pulled directly from their original sources, bypassing the NC-licensed aggregation:

| Dataset | License | Size | Fit |
|---|---|---|---|
| [KUQ (Known-Unknown Questions)](https://huggingface.co/datasets/amayuelas/KUQ) | MIT | Multi-file JSONL, categories incl. "future unknowns" | Question-type classifier stress test (F1.1/F1.4 prediction-language detection) |
| **[CoCoNot](https://huggingface.co/datasets/allenai/coconot)** | MIT (verified from the repo's actual LICENSE file — an initial automated HF-card read misreported ODC-BY; treat MIT as correct) | 1,001 eval + **379-row `contrast` split** | The `contrast` split is a should-comply counterpart to the refusal set — same design as `NotInject` for injection detection. Strongest match found for F1.5 (over-refusal) |
| [XSTest](https://huggingface.co/datasets/walledai/XSTest) | CC-BY-4.0 | 450 prompts (250 safe / 200 unsafe) | Secondary F1.5 stress test, smaller and safety- rather than knowledge-boundary-focused |
| [OR-Bench](https://huggingface.co/datasets/bench-llms/or-bench) | CC-BY-4.0 | ~80,000 prompts + a 1,000-item hard subset + a toxic calibration subset | Largest-scale F1.5 test found; the toxic subset gives a genuine-refusal sanity check alongside the over-refusal one |
| [SelfAware](https://github.com/yinzhangyue/SelfAware) | Apache-2.0 | 3,369 questions | General answerable/unanswerable precision check, no boundary metadata |
| FreshQA | Apache-2.0 | 600 time-sensitive questions | Usable but access-friction: requires a one-time manual Google Sheets export before it can be scripted |

**Rejected:** SQuAD 2.0 (CC-BY-SA — same exclusion category as TensorTrust elsewhere in this project, despite being a conceptually strong fit for F1.2/F1.3/F1.6).

**Gap:** F1.2 (coverage window) and F1.3 (entity scope) are genuinely underserved — no public dataset encodes a declared coverage window or entity roster. A real benchmark here needs a dated dataset (FreshQA is the closest fit) paired with a fabricated `KnowledgeBoundary` to generate in-scope/out-of-scope pairs. F1.6 (partial-answer-as-complete) has no matching dataset found at all in this pass.

---

## F2 — Source authority & provenance

Detection: `src/agentfox/provenance.py` — source tiering, freshness SLAs, domain matching, and citation binding (does a claim map to a chunk that actually supports it). Explicitly **not** the same thing as groundedness (answer-vs-context faithfulness), which the project already covers separately.

| Dataset | License | Size | Fit |
|---|---|---|---|
| [HALLMARK](https://github.com/rpatrik96/hallmark) | MIT | 2,526 entries, 14 hallucination types | Direct match for F2.3 (fabricated citation) — citation-existence with sub-checks down to DOI/author/venue; also carries a small retracted-paper subset, a narrow analogue to F2.2 |
| [CRED-1](https://github.com/aloth/cred-1) | CC-BY-4.0 | 2,674 domains | Clearest match for F2.1 (unauthoritative source) — domain-level credibility scores. Negative-list only (known-bad domains), needs pairing with a benign-domain set for full precision/recall |
| [ALCE](https://github.com/princeton-nlp/ALCE) | MIT | ~3,000 questions (ASQA/QAMPARI/ELI5) with citation-quality gold labels | Tests citation-support binding specifically — flagged explicitly as testing only the narrow half of F2.3, **not** source authority; risks double-counting with the existing groundedness scorer if oversold |

**Rejected:** RAGTruth (this is groundedness, the capability F2 is explicitly defined in contrast to — wrong target despite a clean MIT license), FreshQA (tests answer currency against the real world, not source-metadata staleness — wrong mechanism for F2.2 despite the tempting name), NELA-GT-2022 (deaccessioned, copyrighted scraped article text), CAP (no located license or release), Wikipedia "Citation Needed" (no maintained repo with a stated license; underlying text is CC-BY-SA). **Held back, not confirmed:** AmbiFC — the best conceptual fit found for F2.4 (contradictory sources), but its actual data-hosting repo shows `license: null` despite a CC-BY-4.0 claim in the paper; needs direct author confirmation before use.

**Gap:** F2.4 (contradictory sources) has no confirmed-license dataset; F2.6 (source outside declared domain) has no purpose-built dataset at all — would need synthesis from a labeled multi-domain corpus (e.g., CRED-1's categories combined with a domain-tagged text corpus).

---

## Cross-cutting findings

1. **No candidate anywhere matches AgentFox's exact internal data model.** Every capability area has the same shape of gap: public datasets test the general problem (is this citation fake, is this source credible, is this question unanswerable) but none carry the specific declared metadata AgentFox's code actually keys on (coverage windows, entity rosters, source tiers, ACL grants, environment bindings). Building real benchmarks here means layering synthetic metadata onto a real, license-clean corpus — the same pattern already used successfully for the injection-detection corpus growth (round 6's HackAPrompt-informed category additions).
2. **License verification catches real problems, not just paperwork.** Four separate near-misses this round: AbstentionBench (CC-BY-NC despite being the field's standard reference), AgentHarm (MIT label with an added restrictive clause), ai4privacy (tiered commercial license, one variant with no license file at all), and AmbiFC (license claimed in the paper, not actually attached to the data repo). Reading the actual `LICENSE` file, not the badge or the paper's stated terms, found all four.
3. **F3.8 (composed privilege escalation) — our one confirmed-absent failure mode — has a strong, ready-to-use dataset.** InjecAgent's attacker/user-tool split is the closest thing in this whole research pass to a drop-in benchmark for a gap we've already named as genuinely unaddressed in `failure-modes.md`. Worth prioritizing.
4. **PII's default exclusion has a measurable cost, waiting to be measured.** `PERSON`/`LOCATION`/`DATE_TIME` are excluded by default in the Presidio adapter as "noisy" — presidio-research's own synthetic set shows `PERSON` alone is 37% of labeled spans, meaning the honest recall cost of that default is a number we can produce directly, the same kind of disclosed trade-off the injection-detection ensemble work already reports.

## Suggested build order

Matches the commercial-priority reasoning already in `docs/design/gap-analysis.md` (destructive actions and entitlement matter more in an enterprise deployment than injection detection alone), adjusted for what's actually ready to build against:

1. **F3.8 via InjecAgent** — closes the one confirmed gap in the taxonomy, dataset is ready now.
2. **F3 broadly via `gretelai/synthetic_text_to_sql` + AgentDojo** — highest commercial priority, datasets ready now, mirrors the existing SQL-parsing test discipline.
3. **PII via presidio-research + gretelai multilingual** — ready now, produces the honest "what does excluding PERSON/LOCATION cost" number.
4. **F4 via ConfAIde + PrivacyLens + AgentLeak** — highest commercial value per the codebase's own stated hypothesis, though the "exact match" dataset shape doesn't exist yet — start with what's available and name the gap explicitly in the writeup, the same way `data_generalization/README.md` does for `trustairlab.json`'s label-noise caveat.
5. **F1 via KUQ + CoCoNot** — ready now for F1.1/F1.4/F1.5; F1.2/F1.3/F1.6 need synthetic fixtures, scope that as a second pass.
6. **F2 via HALLMARK + CRED-1** — ready now; ALCE only if the "citation-binding, not source-authority" distinction is kept explicit in any writeup.
7. **Secrets via CredData/SecretBench** — lowest priority of what's covered here, both carry real caveats (mixed provenance, access gate) worth resolving before committing engineering time.
