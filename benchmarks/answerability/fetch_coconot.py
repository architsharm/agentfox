"""Fetches allenai/coconot's `contrast` config test split (MIT — verified via the
HF API's `cardData.license`) and writes it to `data/coconot_contrast.json`.

    uv run --with pyarrow python -m benchmarks.answerability.fetch_coconot

Source: https://huggingface.co/datasets/allenai/coconot
Config: contrast, split test — 379 rows, `{id, category, subcategory, prompt,
        response}`. These are the should-comply counterpart to CoCoNot's main
        refusal set (safety concerns, incomplete requests, unsupported
        requests) — superficially similar to a genuine refusal case, but a
        well-behaved assistant should answer them, not refuse.

None of CoCoNot's categories are about a knowledge boundary (F1's actual
scope) — they're about safety, request completeness, and modality limits, all
governed elsewhere in AgentFox or not at all. That's exactly why this is a
useful *negative* control for `answerability.py`: it's real-world-shaped
prompt text with zero connection to prediction/opinion/coverage/entity/topic
boundaries, so any of them getting an `answerable=False` verdict is a clean
signal of the deterministic classifiers misfiring on ordinary text, not a
disagreement about scope (contrast with KUQ's `controversial` category, which
*is* a scope disagreement — see run_kuq_benchmark.py).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

try:
    import pyarrow.parquet as pq
except ImportError:
    pq = None

DATA_DIR = Path(__file__).parent / "data"
URL = (
    "https://huggingface.co/datasets/allenai/coconot"
    "/resolve/refs%2Fconvert%2Fparquet/contrast/test/0000.parquet"
)


def main() -> None:
    if pq is None:
        raise SystemExit(
            "Run with: uv run --with pyarrow python -m benchmarks.answerability.fetch_coconot"
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = DATA_DIR / "_coconot_contrast_raw.parquet"
    subprocess.run(["curl", "-sL", "--fail", "-o", str(raw_path), URL], check=True)

    table = pq.read_table(raw_path)
    rows = table.to_pylist()
    print(f"Fetched {len(rows)} rows from coconot contrast/test")

    out = [
        {"prompt": r["prompt"], "category": r["category"], "subcategory": r["subcategory"]}
        for r in rows
    ]
    out_path = DATA_DIR / "coconot_contrast.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {out_path}")

    raw_path.unlink()


if __name__ == "__main__":
    main()
