"""Draw the stratified SQL label-audit sample (reviewer 21B.1). Offline.

    WAITI_BENCH_ROOT=<worktree at 723fcec> python3 artifact/sql_audit_sample.py

Strata: dataset category x dataset label. Fixed seed. Writes two files:
  audit/sql_audit_blind.json  audit id + SQL text only, shuffled (what the annotator sees)
  audit/sql_audit_key.json    audit id -> benchmark row id (not opened until labelling is done)
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BROOT = Path(os.environ.get("WAITI_BENCH_ROOT", ROOT))
SEED = 20261023
PLAN = {  # (category, dataset label) -> rows drawn
    ("natural_dml", False): 25,
    ("natural_dml", True): 20,
    ("natural_ddl", False): 25,
    ("natural_ddl", True): 20,
    ("adversarial_unbounded", True): 15,
    ("adversarial_tautology", True): 15,
}

data = json.loads((BROOT / "benchmarks/action_safety/data/action_safety.json").read_text())
strata: dict[tuple[str, bool], list[tuple[str, str]]] = {k: [] for k in PLAN}
for split in ("train", "test"):
    for cat, rows in data[split].items():
        for i, r in enumerate(rows):
            key = (cat, bool(r["expect_blocked"]))
            if key in strata:
                strata[key].append((f"{split}_{cat}/{i}", r["sql"]))
rng = random.Random(SEED)
picked = []
for key, n in PLAN.items():
    picked += rng.sample(strata[key], n)
rng.shuffle(picked)
blind = [{"audit_id": f"a{j:03d}", "sql": sql} for j, (_, sql) in enumerate(picked)]
key = {f"a{j:03d}": rid for j, (rid, _) in enumerate(picked)}
(HERE / "audit").mkdir(exist_ok=True)
(HERE / "audit/sql_audit_blind.json").write_text(json.dumps(blind, indent=1) + "\n")
(HERE / "audit/sql_audit_key.json").write_text(
    json.dumps(
        {
            "seed": SEED,
            "plan": {f"{c}|{lab}": n for (c, lab), n in PLAN.items()},
            "stratum_sizes": {f"{c}|{lab}": len(v) for (c, lab), v in strata.items()},
            "key": key,
        },
        indent=1,
    )
    + "\n"
)
print(len(blind), {f"{c}|{lab}": len(v) for (c, lab), v in strata.items()})
