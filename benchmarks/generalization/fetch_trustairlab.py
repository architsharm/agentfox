"""Fetches TrustAIRLab/in-the-wild-jailbreak-prompts's HF-hosted parquet exports
and writes a fixed, reproducible sample to `data/trustairlab.json`.
Already run once — the output is committed so `run_generalization_benchmark.py`
works offline — but this is here so the fetch itself is reproducible too, not
just the scoring.

    uv run --with pyarrow python -m benchmarks.generalization.fetch_trustairlab

Uses the dataset's auto-converted parquet files directly (one HTTP GET per
config, via the `refs/convert/parquet` ref HF publishes for every dataset)
rather than the datasets-server `/rows` API paginated 100 rows at a time — the
regular_2023_12_25 config alone is 13,735 rows / 138 paginated requests, which
trips Hugging Face's CloudFront rate limit (429) well before finishing.

Two configs:

  - jailbreak_2023_12_25 (1,405 rows) — real, organic jailbreak prompts scraped
    from Discord/Reddit/etc. communities. All positives; used in full.
  - regular_2023_12_25 (13,735 rows) — genuine organic prompts from the same
    source communities that were NOT flagged as jailbreaks. All negatives; a
    fixed 1,405-row `random.seed(20260828)` sample (same seed used for the SPML
    sample, matching this project's own reproducibility convention), so the
    combined file is balanced 50/50 like the other generalization datasets.
"""

from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
BASE_URL = (
    "https://huggingface.co/datasets/TrustAIRLab/in-the-wild-jailbreak-prompts"
    "/resolve/refs%2Fconvert%2Fparquet"
)
SEED = 20260828


def fetch_config(config: str) -> list[dict]:
    import pyarrow.parquet as pq

    dest = DATA_DIR / f"_{config}.parquet"
    subprocess.run(
        ["curl", "-sL", f"{BASE_URL}/{config}/train/0000.parquet", "-o", str(dest)],
        check=True,
    )
    table = pq.read_table(dest)
    rows = table.to_pylist()
    dest.unlink()
    return rows


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    jailbreak_rows = fetch_config("jailbreak_2023_12_25")
    print(f"jailbreak_2023_12_25: {len(jailbreak_rows)} rows fetched")

    regular_rows = fetch_config("regular_2023_12_25")
    print(f"regular_2023_12_25: {len(regular_rows)} rows fetched")

    rng = random.Random(SEED)
    regular_sample = rng.sample(regular_rows, min(len(jailbreak_rows), len(regular_rows)))

    combined = [
        {"text": r["prompt"], "label": 1, "platform": r.get("platform"), "source": r.get("source")}
        for r in jailbreak_rows
    ] + [
        {"text": r["prompt"], "label": 0, "platform": r.get("platform"), "source": r.get("source")}
        for r in regular_sample
    ]
    rng.shuffle(combined)

    (DATA_DIR / "trustairlab.json").write_text(json.dumps(combined, indent=2))
    print(
        f"wrote {len(combined)} rows ({len(jailbreak_rows)} positive / {len(regular_sample)} negative)"
    )


if __name__ == "__main__":
    main()
