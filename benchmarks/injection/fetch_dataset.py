"""Fetches `deepset/prompt-injections` from Hugging Face's public datasets-server API
and writes it to `data/train.json` / `data/test.json`. Already run once — the output
is committed so `run_prompt_injection_benchmark.py` works offline — but this is here
so the fetch itself is reproducible too, not just the scoring.

    python -m benchmarks.injection.fetch_dataset
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATASET = "deepset/prompt-injections"
SPLITS = {"train": 546, "test": 116}


def fetch_split(split: str, total: int) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while offset < total:
        url = (
            "https://datasets-server.huggingface.co/rows"
            f"?dataset={DATASET.replace('/', '%2F')}&config=default&split={split}"
            f"&offset={offset}&length=100"
        )
        out = subprocess.run(["curl", "-s", url], capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        batch = [r["row"] for r in data["rows"]]
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
    return rows


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for split, total in SPLITS.items():
        rows = fetch_split(split, total)
        (DATA_DIR / f"{split}.json").write_text(json.dumps(rows))
        print(f"{split}: {len(rows)} rows")


if __name__ == "__main__":
    main()
