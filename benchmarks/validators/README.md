# Ours, theirs, or both

The Guardrails AI validators are ported into `src/agentfox/capabilities/detection/validators/`.
Where one of them checks for the same thing one of our detectors checks for, this benchmark
decides which a workspace should run: ours, theirs, or both together.

Each component scores every text once. A union ("ours + theirs") is computed from those same
predictions, so it is exactly what switching both on would flag, at no extra run.

| Task | Ours | Theirs (ported) | Data |
|---|---|---|---|
| Injection and jailbreak | `injection.heuristic`, `injection.classifier` | `detect_jailbreak` (their classifier alone; its known-attack leg is off by default because it would compare against our corpus) | deepset held-out test, SPML sample, NotInject (benign only), TrustAIRLab, yanismiraoui (attacks only) |
| Toxicity | `safety.lexicon`, `safety.granite` | `toxic_language`, `bert_toxic`, `nsfw_text`, `profanity_free` | ToxicChat 0124 test split (`lmsys/toxic-chat`) |

Components that cannot run on the machine (a missing library or model weights) are listed under
`skipped` in the result file rather than scored as zero.

**What these numbers may not be used for.** They choose defaults. They are never used to write
or edit a pattern, a corpus entry or a threshold in the product; doing that would make every
later run of this benchmark a measurement of its own training data.

```bash
python -m benchmarks.validators.fetch_toxicchat   # CC-BY-NC-4.0: downloaded to var/, never committed
PYTHONPATH=src python -m benchmarks.validators.run_comparison --task injection --limit 500
PYTHONPATH=src python -m benchmarks.validators.run_comparison --task toxicity --limit 2000
```

`--limit` takes a seeded, label-stratified sample per dataset (seed `20261012`). Results are
written to `results/comparison_<task>.json` with Wilson 95% intervals and median latency per
component.

## Results (2026-10-12, CPU, threshold 0.5)

**Injection and jailbreak**: 1,955 rows (500 per dataset where larger). From
[`results/comparison_injection.json`](results/comparison_injection.json):

| Arm | Side | Precision | Recall | F1 | False positives on benign |
|---|---|---|---|---|---|
| `injection.classifier` | ours | 82.9 | 95.3 | 88.7 | 23.2% |
| classifier + `detect_jailbreak` | both | 81.2 | 95.8 | 87.9 | 26.3% |
| `detect_jailbreak` | theirs | 79.7 | 15.9 | 26.6 | 4.8% |
| `injection.heuristic` + `detect_jailbreak` | both | 78.4 | 20.6 | 32.6 | 6.7% |
| `injection.heuristic` | ours | 77.4 | 9.1 | 16.2 | 3.1% |

Their classifier adds 0.5 points of recall to ours for 3.1 points more false positives, so it
is not added to ours by default. Without our classifier, it more than doubles what the
heuristic alone catches (20.6% vs 9.1%) at 6.7% false positives. That makes it the better
light option where the larger model cannot be installed, and it is offered as
`validator.detect_jailbreak`. Our classifier's false positives are concentrated on NotInject
(41.3% at this threshold), a set built from benign prompts that use attack words; that is
a known over-defence and a target for the accuracy work, not something this run changes.

**Toxicity**: 2,000 ToxicChat prompts (seeded sample). From
[`results/comparison_toxicity.json`](results/comparison_toxicity.json):

| Arm | Side | Precision | Recall | F1 | False positives |
|---|---|---|---|---|---|
| `safety.lexicon` + `bert_toxic` | both | 63.5 | 28.2 | 39.0 | 1.2% |
| `bert_toxic` | theirs | 60.3 | 24.6 | 35.0 | 1.2% |
| `nsfw_text` | theirs | 24.5 | 87.3 | 38.3 | 20.6% |
| `safety.lexicon` | ours | 100.0 | 3.5 | 6.8 | 0.0% |

Our lexicon is precise and misses most of what people actually type. `bert_toxic` finds
seven times as much at a 1.2% false-positive rate, and together they do best, so
`validator.bert_toxic` is offered as an every-request check to run beside the lexicon.
`nsfw_text` flags one benign prompt in five; it stays available as a rule but is not
offered as an every-request check.

Not scored here: `toxic_language` (needs `detoxify`), `profanity_free` (needs
`alt-profanity-check`), `safety.granite` (weights not on this machine) and the LLM judges
(no judgment tier enabled on the benchmark machine).
