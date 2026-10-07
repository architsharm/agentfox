"""Helpers shared by more than one benchmark script.

Only code that was copied verbatim between scripts lives here. Each script still owns its
own ground truth, scoring rules and result format; nothing in this package decides what
counts as a hit.
"""

from benchmarks._common.db import wipe_db
from benchmarks._common.fetch import fetch
from benchmarks._common.spans import (
    merge_counts,
    pred_spans,
    prf1,
    score_row_with_exclusions,
    summarize,
)

__all__ = [
    "fetch",
    "merge_counts",
    "pred_spans",
    "prf1",
    "score_row_with_exclusions",
    "summarize",
    "wipe_db",
]
