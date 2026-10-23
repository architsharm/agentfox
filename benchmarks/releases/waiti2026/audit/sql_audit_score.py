"""Score the blind SQL relabelling against the benchmark label and the parser (reviewer 21B.1).

    python3 artifact/sql_audit_score.py

Reads audit/sql_audit_labels.json (blind labels), audit/sql_audit_key.json and the stored
per-row parser decisions; writes audit/sql_audit_result.json.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
lab = json.loads((HERE / "audit/sql_audit_labels.json").read_text())
key = json.loads((HERE / "audit/sql_audit_key.json").read_text())
rows = {
    r["id"]: r
    for r in json.loads((ROOT / "internal/scripts/as_jev_results.json").read_text())["rows"]
}


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(100 * max(0.0, (c - m) / d), 1), round(100 * min(1.0, (c + m) / d), 1)]


per_stratum: dict[str, dict] = {}
dis = []
agree_label = agree_parser = 0
for aid, rid in key["key"].items():
    r = rows[rid]
    mine, want, parser = lab["labels"][aid], bool(r["want"]), bool(r["detector"])
    cat = rid.split("/")[0].split("_", 1)[1]
    s = per_stratum.setdefault(f"{cat}|{want}", {"n": 0, "agree_label": 0, "agree_parser": 0})
    s["n"] += 1
    s["agree_label"] += mine == want
    s["agree_parser"] += mine == parser
    agree_label += mine == want
    agree_parser += mine == parser
    if mine != want or mine != parser:
        dis.append(
            {
                "audit_id": aid,
                "row": rid,
                "mine": mine,
                "label": want,
                "parser": parser,
                "note": lab["notes"].get(aid, ""),
            }
        )
n = len(key["key"])
# Reweight to the population: each stratum's agreement rate times its share of the SQL rows.
sizes = key["stratum_sizes"]
tot = sum(sizes.values())
weighted = sum(sizes[k] / tot * v["agree_label"] / v["n"] for k, v in per_stratum.items())
noted = sum(1 for a in key["key"] if a in lab["notes"])
contested = {k: len(v) for k, v in lab["contested"].items()}
# contested items by stratum, reweighted to the population
cont_ids = {a for v in lab["contested"].values() for a in v}
cont_by = {}
for aid, rid in key["key"].items():
    cat = rid.split("/")[0].split("_", 1)[1]
    k = f"{cat}|{bool(rows[rid]['want'])}"
    cont_by[k] = cont_by.get(k, 0) + (aid in cont_ids)
cont_weighted = sum(sizes[k] / tot * cont_by.get(k, 0) / per_stratum[k]["n"] for k in per_stratum)
res = {
    "seed": key["seed"],
    "n": n,
    "annotator": lab["annotator"],
    "agree_with_label": agree_label,
    "agree_with_label_ci": wilson(agree_label, n),
    "agree_with_parser": agree_parser,
    "population_weighted_agreement_pct": round(100 * weighted, 1),
    "items_with_a_definition_note": noted,
    "contested": contested,
    "contested_n": len(cont_ids),
    "contested_by_stratum": cont_by,
    "contested_population_weighted_pct": round(100 * cont_weighted, 1),
    "per_stratum": per_stratum,
    "disagreements": dis,
}
(HERE / "audit/sql_audit_result.json").write_text(json.dumps(res, indent=1) + "\n")
print(json.dumps(res, indent=1))
