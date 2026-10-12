"""Download the ToxicChat test split (lmsys/toxic-chat, version 0124).

5,083 real user prompts to an LLM demo, each labelled toxic or not by annotators.
Licence CC-BY-NC-4.0, so it is downloaded to `var/benchmarks/` (gitignored) and never
committed; only the scores derived from it are.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

URL = (
    "https://huggingface.co/datasets/lmsys/toxic-chat/resolve/main/"
    "data/0124/toxic-chat_annotation_test.csv"
)
OUT = Path(__file__).resolve().parents[2] / "var" / "benchmarks" / "toxicchat_test.csv"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=60) as resp:  # noqa: S310 - fixed https URL
        OUT.write_bytes(resp.read())
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
