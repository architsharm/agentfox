# Data source

`train.json` / `test.json` are `deepset/prompt-injections`, fetched verbatim from
Hugging Face's public datasets-server API (see `../fetch_dataset.py`).

- Source: https://huggingface.co/datasets/deepset/prompt-injections
- License: apache-2.0
- Schema: `{"text": str, "label": int}` — `label` is `1` for prompt injection /
  jailbreak, `0` for benign.
- Size: 546 train + 116 test = 662 total examples.

AgentFox's detector is a hand-written heuristic pipeline, not a model trained on
this (or any) dataset, so `../run_prompt_injection_benchmark.py` scores both splits
combined — there's no train/test leakage concern for code that was never fit to the
data in the first place.
