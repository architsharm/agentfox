# F4 — entitlement & disclosure control: a self-constructed scenario benchmark

**Read this before the numbers below**: this is not the same kind of benchmark as `benchmarks/pii/`, `benchmarks/action_safety/`, or `benchmarks/answerability/`. Those score existing code against a public dataset's *own* independently-authored ground truth. No public dataset supplies labels in the shape `src/agentfox/capabilities/grounding/entitlement.py` needs — confirmed directly by investigating AgentLeak and PrivacyLens for `docs/evaluation/dataset-sourcing.md`, and independently re-confirmed for the adjacent F2 capability in `benchmarks/source_authority/README.md`. What follows instead uses [PrivacyLens](https://github.com/SALT-NLP/PrivacyLens) (MIT) for its real, varied, human-authored *scenario content* — but the actual test (what's granted, what's requested, what's correct) is constructed here, not sourced from PrivacyLens's own labels. See the full methodology in `run_privacylens_benchmark.py`'s docstring.

```bash
uv run python benchmarks/entitlement/fetch_privacylens.py
uv run python benchmarks/entitlement/run_privacylens_benchmark.py
```

## What this tests: purpose limitation (F4.6, GDPR Art. 5(1)(b))

`filter_retrieval(session, principal, chunks, purpose=...)` is supposed to withhold a resource when the caller's stated purpose isn't among the purposes it was granted for. PrivacyLens's 493 vignettes are all, by design, over-sharing scenarios — information retrieved for one purpose (a lawyer's case notes, for internal case work) about to be disclosed through an unrelated channel (a public Facebook post). That structural guarantee (original purpose ≠ disclosure purpose, always) is what gets tested mechanically:

- Each vignette's resource is granted for exactly one purpose: `"original_collection"`.
- **Positive case**: request it for the vignette's own real `transmission_principle` (e.g. `"post it on facebook"`, slugified) — should be withheld.
- **Negative case**: request it for `"original_collection"` itself, same resource, same principal — should be allowed.

## Results, all 493 rows

| Case | Support | Result |
|---|---|---|
| Positive (should withhold) | 493 | **Recall: 100.0%** (493/493) |
| Negative (should allow) | 493 | **False-positive rate: 0.0%** (0/493) |

Full output: [`results/privacylens_summary.json`](results/privacylens_summary.json).

## Read this result for what it actually shows

A perfect score here is the **expected outcome of a correctly-constructed mechanical test**, not evidence of a detector handling hard, ambiguous cases well — unlike the PII or answerability benchmarks, where a real classifier had to generalize across noisy, varied inputs and genuinely could have failed. `filter_retrieval`'s purpose check is a deterministic set-membership comparison (`purpose not in permitted`); given a correctly-constructed positive case, it was always going to fire, and a failure here would have meant a real bug in `entitlement.py`, not a benchmark finding. A score short of 100% would have needed investigating regardless of which side the bug was on.

What this run *does* legitimately establish, and is worth stating plainly: the mechanism doesn't break on **493 genuinely diverse, real, human-authored purpose strings** — everything from `"send a facebook post"` to multi-clause transmission principles with punctuation, mixed case, and domain-specific phrasing (legal, medical, HR, journalism scenarios in PrivacyLens's source material). No slugification collision, no unexpected `fnmatch` behavior, no confound from the `RESTRICTED_CLASSES`/residency/tier checks that also run inside `filter_retrieval` before reaching the purpose check. That's a real, if modest, confirmation — not the kind of precision/recall trade-off finding the rest of this benchmark suite produces.

## What this benchmark does **not** cover

- **F4.1/F4.2** (entitlement/clearance-tier filtering) and **F4.4** (aggregation disclosure) — untested here; would need a similarly self-constructed scenario set, not attempted in this pass.
- **AgentLeak** (MIT) — investigated and set aside for `docs/evaluation/dataset-sourcing.md`'s F4 work: its `allowed_set.fields`/`forbidden_fields` schema operates at **field-level redaction within a single record** ("disclose name/visit_date but not ssn/diagnosis"), a different granularity than `entitlement.py`'s **resource-level** ACL model (a whole retrieved chunk is visible or withheld, not individual fields within it). Scoring it would require building a new field-level redaction mechanism, out of scope for benchmarking existing code.
- **ConfAIde** — not investigated this pass; remains a candidate for F4.5 (inference disclosure) and F4.6 in a future round.
- This benchmark used **all 493 rows as positive+negative pairs from the same construction** — there's no independent, harder negative-control set the way `benchmarks/answerability/`'s CoCoNot split provides. A future pass could strengthen this by drawing negative controls from an unrelated source instead of the mechanical complement used here.
