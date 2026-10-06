"""Fetches SALT-NLP/PrivacyLens's `main_data.json` (MIT — verified via the repo's
actual LICENSE file, fetched directly) and writes it unmodified to
`data/privacylens.json`.

    uv run python benchmarks/entitlement/fetch_privacylens.py

Source: https://github.com/SALT-NLP/PrivacyLens
File:   data/main_data.json (493 rows)

Each row is a contextual-integrity vignette: a data type, a data subject, a data
sender, a target recipient, and a "transmission principle" (the disclosure
channel/purpose) — e.g. a lawyer's confidential case notes (retrieved for
internal case work) about to be posted publicly to Facebook. See
`run_privacylens_benchmark.py`'s docstring for how this real, human-authored
scenario content is turned into a concrete test of
`src/agentfox/capabilities/grounding/entitlement.py::filter_retrieval`'s purpose-limitation check — a
different, self-constructed kind of benchmark than the off-the-shelf-labeled
datasets used elsewhere in this project, and disclosed as such.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
URL = "https://raw.githubusercontent.com/SALT-NLP/PrivacyLens/main/data/main_data.json"
LICENSE_URL = "https://raw.githubusercontent.com/SALT-NLP/PrivacyLens/main/LICENSE"


def _fetch(url: str) -> str:
    result = subprocess.run(
        ["curl", "-sL", "--fail", url], capture_output=True, text=True, check=True
    )
    return result.stdout


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    license_text = _fetch(LICENSE_URL)
    if "MIT License" not in license_text:
        raise SystemExit(
            "PrivacyLens LICENSE no longer reads as MIT — re-verify before using this data."
        )

    raw = _fetch(URL)
    rows = json.loads(raw)
    print(f"Fetched {len(rows)} rows from PrivacyLens main_data.json")

    out_path = DATA_DIR / "privacylens.json"
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
