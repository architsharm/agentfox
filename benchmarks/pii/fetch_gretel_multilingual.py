"""Fetches gretelai/synthetic_pii_finance_multilingual's HF-hosted parquet export
(`test` split only — see below), filters `pii_spans` down to well-formed rows, and
writes a flat JSON file to `data/gretel_multilingual_pii.json`.

    uv run --with pyarrow python -m benchmarks.pii.fetch_gretel_multilingual

License: Apache-2.0, per the dataset's HF card (`cardData.license`) — verified via
`https://huggingface.co/api/datasets/gretelai/synthetic_pii_finance_multilingual`.
HF-hosted datasets don't ship a fetchable repo `LICENSE` file the way a GitHub repo
does (no equivalent of `fetch_presidio_research.py`'s runtime LICENSE check here);
the license tag is the authoritative declaration HF itself surfaces for the
dataset, same as how `fetch_gretel_sql.py` treats `gretelai/synthetic_text_to_sql`'s
Apache-2.0 tag.

Full-length synthetic financial documents (EDI messages, invoices, statements,
contracts — 7 document types) across 7 languages (English, French, German, Dutch,
Spanish, Italian, Swedish), each with span-labeled PII (`pii_spans`, a JSON string
of `{start, end, label}` dicts, 27 distinct label types).

Only the `test` split (5,594 rows) is fetched — ground truth here is the dataset's
own direct annotation (not something derived via our own regex/parser the way
`fetch_gretel_sql.py`'s SQL ground truth is), so there's no train/test "catch a
ground-truth bug before trusting numbers" concern the way the SQL benchmark had;
`test` is used simply because it's the split intended for evaluation.
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
PARQUET_URL = (
    "https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual"
    "/resolve/refs%2Fconvert%2Fparquet/default/test/0000.parquet"
)


def main() -> None:
    if pq is None:
        raise SystemExit(
            "Run with: uv run --with pyarrow python -m benchmarks.pii.fetch_gretel_multilingual"
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = DATA_DIR / "_gretel_multilingual_raw.parquet"
    subprocess.run(["curl", "-sL", "--fail", "-o", str(raw_path), PARQUET_URL], check=True)

    table = pq.read_table(raw_path)
    rows = table.to_pylist()
    print(f"Fetched {len(rows)} rows")

    out = []
    skipped = 0
    for row in rows:
        try:
            spans = json.loads(row["pii_spans"])
        except (TypeError, ValueError):
            skipped += 1
            continue
        out.append(
            {
                "document_type": row["document_type"],
                "language": row["language"],
                "text": row["generated_text"],
                "spans": [
                    {"start": s["start"], "end": s["end"], "label": s["label"]} for s in spans
                ],
            }
        )

    print(f"Kept {len(out)} rows, skipped {skipped} with unparseable pii_spans")

    out_path = DATA_DIR / "gretel_multilingual_pii.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {out_path}")

    raw_path.unlink()


if __name__ == "__main__":
    main()
