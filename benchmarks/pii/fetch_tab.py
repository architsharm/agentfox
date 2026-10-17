"""Fetches the Text Anonymization Benchmark (TAB)'s `echr_test.json` split (MIT —
LICENSE verified by fetching it directly) and writes it unmodified to
`data/tab_echr_test.json`.

    uv run python -m benchmarks.pii.fetch_tab

Source: https://github.com/NorskRegnesentral/text-anonymization-benchmark
File:   echr_test.json (127 real European Court of Human Rights judgments,
        multi-annotator span-labeled for PII/re-identification risk)

Only `test` (127 rows) is fetched — same reasoning as
`fetch_gretel_multilingual.py`: ground truth here is the dataset's own direct,
human annotation, not something derived via a parser/regex we wrote, so there's
no train/test "catch a ground-truth bug before trusting numbers" concern.
`train` (1,014 rows) and `dev` (127 rows) exist and could extend this later.

This is the one PII dataset in this benchmark suite built from **real** text
(anonymized ECHR case law, not synthetic) — the whole reason it was sourced was
to stress-test Presidio's PERSON/LOCATION NER on natural legal prose rather than
templated sentences (Dataset 1) or synthetic financial documents (Dataset 2).
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks._common import fetch

DATA_DIR = Path(__file__).parent / "data"
BASE = "https://raw.githubusercontent.com/NorskRegnesentral/text-anonymization-benchmark/master"
LICENSE_URL = f"{BASE}/LICENSE.txt"
TEST_URL = f"{BASE}/echr_test.json"


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    license_text = fetch(LICENSE_URL)
    if "MIT License" not in license_text:
        raise SystemExit(
            "TAB LICENSE.txt no longer reads as MIT — re-verify before using this data."
        )

    raw = fetch(TEST_URL)
    rows = json.loads(raw)
    print(f"Fetched {len(rows)} rows from TAB echr_test.json")

    out_path = DATA_DIR / "tab_echr_test.json"
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
