"""Fetches Microsoft presidio-research's `synth_dataset_v2.json` (MIT — LICENSE
verified by fetching it directly, see below) and writes it unmodified to
`data/synth_dataset_v2.json`.

    uv run python -m benchmarks.pii.fetch_presidio_research

Source: https://github.com/microsoft/presidio-research
File:   data/synth_dataset_v2.json (1,500 span-labeled synthetic sentences)

This is a synthetic, template-generated dataset (Presidio's own data generator),
not real personal data — each row is `{full_text, masked, spans: [{entity_type,
entity_value, start_position, end_position}], template_id, metadata}`.

No filtering or sampling is done here — all 1,500 rows are kept. The scoring
script (`run_presidio_research_benchmark.py`) is the one that scopes rows down to
the entity types AgentFox's PII detectors actually claim to cover; that scoping
decision belongs with the scorer, not the fetcher, so the raw dataset stays
untouched and re-usable for a wider comparison later if needed.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks._common import fetch

DATA_DIR = Path(__file__).parent / "data"
URL = (
    "https://raw.githubusercontent.com/microsoft/presidio-research"
    "/master/data/synth_dataset_v2.json"
)
LICENSE_URL = "https://raw.githubusercontent.com/microsoft/presidio-research/master/LICENSE"


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    license_text = fetch(LICENSE_URL)
    if "MIT License" not in license_text:
        raise SystemExit(
            "presidio-research LICENSE no longer reads as MIT — re-verify before using this data."
        )

    raw = fetch(URL)
    rows = json.loads(raw)
    print(f"Fetched {len(rows)} rows from presidio-research/synth_dataset_v2.json")

    out_path = DATA_DIR / "synth_dataset_v2.json"
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
