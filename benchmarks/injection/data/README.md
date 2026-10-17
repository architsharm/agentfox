# Data source

`train.json` / `test.json` are `deepset/prompt-injections`, fetched verbatim from
Hugging Face's public datasets-server API (see `../fetch_dataset.py`).

- Source: https://huggingface.co/datasets/deepset/prompt-injections
- License: apache-2.0
- Schema: `{"text": str, "label": int}` — `label` is `1` for prompt injection /
  jailbreak, `0` for benign.
- Size: 546 train + 116 test = 662 total examples.

AgentFox's detector is a hand-written heuristic pipeline, not a trained model, but
its patterns *were* written by reading this dataset's misses, so the splits are not
interchangeable:

- **`train.json` was used for development.** Patterns were broadened by reading its
  false negatives. Train and combined numbers therefore include data the patterns were
  fitted to, and are reported for completeness only.
- **`test.json` is the held-out split, and the only number to quote.** One past
  round (commit `10fc1b90`) also read the held-out misses and added patterns for
  them, which inflated held-out heuristic recall from 16.7% to 26.7%. In October 2026
  those patterns, the similarity-corpus entries written alongside them, and patterns
  that copied single training rows were removed, and the benchmark was re-run.

Rule for changes: never write a pattern or corpus entry after reading `test.json`.
