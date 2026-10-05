"""Where the external judgment-tier corpora live on disk.

SafePyramid, ATBench (three releases) and R-Judge are third-party datasets, so they are
not committed. Every script that reads them resolves the location here:

    AGENTFOX_JEV_DATA=/path/to/corpora   # optional; defaults to local/datasets/jev-corpora

Expected layout under that directory (fetch instructions: docs/jev-datasets.md):

    safepyramid.json          ByteDance/SafePyramid, benchmark.json
    at_ATBench_test.json      AI45Research/ATBench, test split
    at_ATBench500_test.json   AI45Research/ATBench (ATBench500 release), test split
    at_claw.json              AI45Research/ATBench-Claw
    rjudge/data__*.json       Lordog/R-Judge, one file per category
    SHA256SUMS                checksums of the copy the published numbers were run on
"""

from __future__ import annotations

import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT = REPO / "local" / "datasets" / "jev-corpora"


def data_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("AGENTFOX_JEV_DATA", DEFAULT)).expanduser()


def require(path: pathlib.Path) -> pathlib.Path:
    """Fail with the fetch instructions rather than a bare FileNotFoundError."""
    if not path.exists():
        raise SystemExit(
            f"missing corpus: {path}\n"
            "Set AGENTFOX_JEV_DATA or fetch the corpora as described in docs/jev-datasets.md."
        )
    return path
