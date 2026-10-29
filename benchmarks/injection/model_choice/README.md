# Which prompt-injection model: PIGuard or Meta Prompt Guard 2

PIGuard catches the most injections: **68.3% held-out recall at 100% precision**, against 20.0% for Prompt Guard 2 86M and 16.7% for Prompt Guard 2 22M. Prompt Guard 2 flags far less benign text: **3.5% and 0%** of NotInject, against PIGuard's 11.5%. PIGuard stays the default; Prompt Guard 2 is an option in `agentfox up` for teams that want fewer false alarms.

Each model ran as `injection.classifier` beside `injection.heuristic`, alone (the secondary backstop off), at its own published default threshold: 0.5 for PIGuard, 0.9 for Prompt Guard 2 (LlamaFirewall's `PromptGuardScanner` default). Higher recall is better; for NotInject, fewer false positives is better.

| Model | Held-out injections (deepset) | SPML | Multilingual (yanismiraoui) | TrustAIRLab | NotInject false positives |
|---|---|---|---|---|---|
| **PIGuard** (default) | **68.3%** at 100% precision | 29.6% | **76.0%** | **89.2%** at 76.4% precision | 39 of 339 (11.5%) |
| Meta Prompt Guard 2 86M | 20.0% at 100% precision | **38.4%** | 44.7% | 70.8% at 67.4% precision | 12 of 339 (3.5%) |
| Meta Prompt Guard 2 22M | 16.7% at 100% precision | 11.2% | 7.4% | 45.5% at 78.5% precision | **0 of 339 (0%)** |
| Pattern checks alone (no model) | 16.7% at 100% precision | 9.6% | 0.9% | 24.1% at 74.0% precision | 0 of 339 |

Source: [`results/summary.json`](results/summary.json), with each model's full benchmark output in `results/<model>_{injection,generalization}_summary.json`. SPML, yanismiraoui and NotInject carry no false positives on their injection side; only TrustAIRLab mixes benign and attack prompts.

## Reading it

- **On the held-out set Prompt Guard 2 22M adds nothing over the pattern checks.** It is English-focused, and the deepset set includes German injections. It flags an English "ignore all previous instructions" at 0.998 and the same sentence in German at 0.003.
- **Prompt Guard 2 86M is multilingual and the stronger of the two.** It beats PIGuard on SPML, and its false-positive rate is a third of PIGuard's.
- **TrustAIRLab is long, mixed text.** On a laptop CPU, 21.8% of Prompt Guard 2 86M's checks there still ran past the long-text budget (4.8% for PIGuard, 1.3% for 22M), so its figure is a lower bound.
- **The thresholds are each model's own published default.** None was tuned on these sets: picking a threshold from the data a model is scored on would fit it to the test.

## Setup

- **Date:** 2026-10-28.
- **Machine:** Apple M1 Pro, CPU only (`AGENTFOX_MODEL_DEVICE=cpu`).
- **Python:** uv-managed Python 3.12 with the locked dependencies.
- **Budget:** the current long-text check budget (`long_text_budget_ms` = 1,000 past 200 characters).
- **Datasets:** the same ones the injection and generalization benchmarks use (`../data`, `../../generalization/data`).

## Reproduce

Prompt Guard 2 is gated: accept Meta's licence on Hugging Face for both models, then fetch the weights with a token that has access.

```bash
export HF_TOKEN=hf_...
AGENTFOX_PROMPT_INJECTION_CLASSIFIER_MODEL=meta-llama/Llama-Prompt-Guard-2-86M agentfox admin detectors pull injection.classifier
AGENTFOX_PROMPT_INJECTION_CLASSIFIER_MODEL=meta-llama/Llama-Prompt-Guard-2-22M agentfox admin detectors pull injection.classifier
AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1 AGENTFOX_MODEL_DEVICE=cpu python -m benchmarks.injection.model_choice.compare_models run var/model_choice
python -m benchmarks.injection.model_choice.compare_models summarize var/model_choice
```
