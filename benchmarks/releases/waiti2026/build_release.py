"""Build the public per-row release for the WAITI 2026 paper. Offline; no model is called.

    WAITI_BENCH_ROOT=<worktree at 723fcec> python3 artifact/build_release.py <out_dir> <piguard_train.json>

Reads the same per-row result files as make_numbers.py and camera_ready_analysis.py
(internal/scripts/*_results.json, artifact/local_tiers.json, benchmark files at 723fcec, the
third-party judgment corpora under local/datasets/jev-corpora) and writes one JSONL file per
dataset to <out_dir>/rows/. Rows carry identifiers, a SHA-256 of the row's text after the
normalisation in `text_sha256`, labels and decisions. No dataset text is written.
"""

from __future__ import annotations

import ast
import glob
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER = HERE.parent
ROOT = HERE.parents[3]
BROOT = Path(os.environ.get("WAITI_BENCH_ROOT", ROOT))
INT = ROOT / "internal" / "scripts"
JEVD = ROOT / "local" / "datasets" / "jev-corpora"
REV = "723fcec"  # agentfox commit the paper's numbers were built from
OUT = Path(sys.argv[1])
PIG_TRAIN = Path(sys.argv[2])
GZIP_OVER = 5_000_000


# ------------------------------------------------------------------ normalisation and hashing
def normalise(x) -> str:
    """Strings: NFC, CRLF/CR -> LF, strip. Anything else: canonical JSON first, then the same."""
    if not isinstance(x, str):
        x = json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    x = unicodedata.normalize("NFC", x).replace("\r\n", "\n").replace("\r", "\n")
    return x.strip()


def text_sha256(x) -> str:
    return hashlib.sha256(normalise(x).encode("utf-8")).hexdigest()


def overlap_norm(t: str) -> str:  # classifier_overlap.py / dedup_injection.py normalisation
    t = unicodedata.normalize("NFKC", t).lower()
    return " ".join(re.sub(r"[^\w]+|_", " ", t).split())


def rows(name: str) -> list[dict]:
    d = json.loads((INT / name).read_text())
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


def bench(path: str):
    return json.loads((BROOT / path).read_text())


def halves(n: int, seed: int = 11, groups: list | None = None) -> tuple[set, set]:
    """Same as camera_ready_analysis.halves / make_numbers.split_threshold (seed 11)."""
    if groups is None:
        idx = list(range(n))
        random.Random(seed).shuffle(idx)
        return set(idx[: n // 2]), set(idx[n // 2 :])
    keys = sorted(set(groups))
    random.Random(seed).shuffle(keys)
    dev_keys = set(keys[: len(keys) // 2])
    return {i for i in range(n) if groups[i] in dev_keys}, {
        i for i in range(n) if groups[i] not in dev_keys
    }


def splitflag(n: int, groups=None) -> list[str]:
    dev, _ = halves(n, groups=groups)
    return ["dev" if i in dev else "test" for i in range(n)]


def r2(x):
    return None if x is None else round(float(x), 4)


FILES: dict[str, list[dict]] = {}
L = json.loads((HERE / "local_tiers.json").read_text())

# ------------------------------------------------------------------ SQL, payload-box, AgentDojo
AS = rows("as_jev_results.json")
sql = [x for x in AS if x["group"] == "sql"]
pred_cache: dict[str, list] = {}


def preds(split: str) -> list:
    if split not in pred_cache:
        pred_cache[split] = bench(f"benchmarks/action_safety/results/{split}_predictions.json")
    return pred_cache[split]


flags = splitflag(len(sql))
out = []
for k, x in enumerate(sql):
    split, i = x["id"].rsplit("/", 1)
    src = preds(split)[int(i)]
    s = max(x["destructive"], x["unbounded"])
    out.append(
        {
            "dataset": "gretel_text_to_sql",
            "row_key": x["id"],
            "source_id": None,
            "source_path": f"benchmarks/action_safety/results/{split}_predictions.json",
            "source_index": int(i),
            "gretel_split": split.split("_", 1)[0],
            "variant": split.split("_", 1)[1],
            "text_sha256": text_sha256(src["sql"]),
            "source_sql_sha256": text_sha256(src["source_sql"]) if src.get("source_sql") else None,
            "label": bool(x["want"]),
            "code_parser_flag": bool(x["detector"]),
            "jev_scores": {"destructive": r2(x["destructive"]), "unbounded": r2(x["unbounded"])},
            "jev_score": r2(s),
            "jev_flag": s >= 0.5,
            "calib_split": flags[k],
        }
    )
FILES["gretel_text_to_sql"] = out

out = []
for x in (x for x in AS if x["group"] == "payloadbox"):
    split, i = x["id"].rsplit("/", 1)
    src = preds(split)[int(i)]
    out.append(
        {
            "dataset": "payload_box",
            "row_key": x["id"],
            "source_id": None,
            "source_path": f"benchmarks/action_safety/results/{split}_predictions.json",
            "source_index": int(i),
            "primary_source": src.get("primary_source"),
            "authored_by_us": bool(src.get("authored")),
            "text_sha256": text_sha256(src["value"]),
            "label": bool(x["want"]),
            "code_parser_flag": bool(x["detector"]),
            "jev_scores": {"injection": r2(x["injection"])},
            "jev_score": r2(x["injection"]),
            "jev_flag": x["injection"] >= 0.5,
        }
    )
FILES["payload_box"] = out

calls = bench("benchmarks/action_safety/data/agentdojo_calls.json")
e2e = bench("benchmarks/agentdojo_e2e/results/agentdojo_e2e_results.json")["predictions"]
e2e_by = {}
for cond in ("detectors_off", "detectors_on"):
    for cat in ("user", "injection"):
        lst = [p for p in e2e[cond] if p["category"] == cat]
        assert len(lst) == len(calls[cat])
        for i, p in enumerate(lst):
            c = calls[cat][i]
            assert (p["suite"], p["task_id"], p["function"]) == (
                c["suite"],
                c["task_id"],
                c["function"],
            )
            e2e_by[(cond, cat, i)] = p
seen, keep = set(), set()
for kind in ("injection", "user"):
    for i, c in enumerate(calls[kind]):
        key = (c["suite"], c["task_id"], c["function"], json.dumps(c["args"], sort_keys=True))
        if key not in seen:
            seen.add(key)
            keep.add(f"agentdojo_{kind}/{i}")
ad_all = [x for x in AS if x["group"] == "agentdojo"]
ad_unique = [x for x in ad_all if x["id"] in keep]
assert len(ad_unique) == 384
ad_flag = dict(zip([x["id"] for x in ad_unique], splitflag(len(ad_unique)), strict=True))
out = []
for x in ad_all:
    split, i = x["id"].rsplit("/", 1)
    cat = split.split("_", 1)[1]
    c = calls[cat][int(i)]
    off, on = e2e_by[("detectors_off", cat, int(i))], e2e_by[("detectors_on", cat, int(i))]
    out.append(
        {
            "dataset": "agentdojo",
            "row_key": x["id"],
            "source_id": f"{c['suite']}/{c['task_id']}/{c['function']}",
            "source_path": "benchmarks/action_safety/data/agentdojo_calls.json",
            "source_index": int(i),
            "source_list": cat,
            "text_sha256": text_sha256({"function": c["function"], "args": c["args"]}),
            "in_paper_unique_calls": x["id"] in keep,
            "label": bool(x["want"]),
            "code_parser_flag": bool(x["detector"]),
            "jev_scores": {"harmful": r2(x["harmful"])},
            "jev_score": r2(x["harmful"]),
            "jev_flag": x["harmful"] >= 0.5,
            "provenance_replay": {
                "impact": off["impact"],
                "verdict": off["effective_verdict"],
                "contained": bool(off["contained"]),
                "verdict_detectors_on": on["effective_verdict"],
                "contained_detectors_on": bool(on["contained"]),
            },
            "calib_split": ad_flag.get(x["id"]),
        }
    )
FILES["agentdojo"] = out

# ------------------------------------------------------------------ external injection sets
pig = json.loads(PIG_TRAIN.read_bytes())
pig_all = {overlap_norm(r["prompt"]) for r in pig if isinstance(r.get("prompt"), str)}
pig_jack = {overlap_norm(r["prompt"]) for r in pig if r.get("source") == "jailbreak-classification"}
dtrain = bench("benchmarks/data/train.json")
dtest = bench("benchmarks/data/test.json")
INJ = {
    "deepset": (dtrain + dtest, None),
    "spml": (
        bench("benchmarks/data_generalization/spml_sample.json"),
        "benchmarks/data_generalization/spml_sample.json",
    ),
    "yanismiraoui": (
        bench("benchmarks/data_generalization/yanismiraoui.json"),
        "benchmarks/data_generalization/yanismiraoui.json",
    ),
    "trustairlab": (
        bench("benchmarks/data_generalization/trustairlab.json"),
        "benchmarks/data_generalization/trustairlab.json",
    ),
    "notinject": (
        bench("benchmarks/data_generalization/notinject.json"),
        "benchmarks/data_generalization/notinject.json",
    ),
}
HEUR = {
    "deepset": "benchmarks/results/prompt_injection_heuristic_combined_predictions.json",
    "spml": "benchmarks/results_generalization/heuristic_spml_predictions.json",
    "yanismiraoui": "benchmarks/results_generalization/heuristic_yanismiraoui_predictions.json",
    "trustairlab": "benchmarks/results_generalization/heuristic_trustairlab_predictions.json",
    "notinject": "benchmarks/results_generalization/heuristic_notinject_predictions.json",
}
for name, (data, path) in INJ.items():
    hb = {r["text"]: bool(r["predicted"]) for r in bench(HEUR[name])}
    out = []
    for i, r in enumerate(data):
        if name == "deepset":
            sp, si = ("train", i) if i < len(dtrain) else ("test", i - len(dtrain))
            spath = f"benchmarks/data/{sp}.json"
        else:
            spath, si = path, i
        lo = L["injection_open"][f"{name}/{i}"]
        n = overlap_norm(r["text"])
        row = {
            "dataset": name,
            "row_key": f"{name}/{i}",
            "source_id": None,
            "source_path": spath,
            "source_index": si,
            "text_sha256": text_sha256(r["text"]),
            "label": str(r.get("label")) in ("1", "True", "true"),
            "code_patterns_flag": hb[r["text"]],
            "piguard_flag": bool(lo["piguard"]),
            "protectai_flag": bool(lo["protectai"]),
            "in_piguard_train": n in pig_all,
            "in_jackhhao_train": n in pig_jack,
        }
        if name == "deepset":
            row["deepset_split"] = sp
        out.append(row)
    FILES[name] = out

# adaptive attempts (in-house attacker output; payload text is in benchmarks/adaptive/results at 723fcec)
att = bench("benchmarks/adaptive/results/adaptive_attempts.json")
out = []
for x in (x for x in rows("rest_jev_results.json") if x["group"] == "adaptive"):
    i = int(x["id"].split("/")[1])
    a = att[i]
    assert bool(a["success"]) == (not x["detector"])
    out.append(
        {
            "dataset": "adaptive_attempts",
            "row_key": x["id"],
            "source_id": None,
            "source_path": "benchmarks/adaptive/results/adaptive_attempts.json",
            "source_index": i,
            "seed_id": a["seed_id"],
            "attempt": a["attempt"],
            "surface": a["surface"],
            "semantics": a["semantics"],
            "text_sha256": text_sha256(a.get("payload", "")),
            "payload_sha16": a.get("payload_sha"),
            "label": True,
            "code_shipped_flag": bool(x["detector"]),
            "escaped_shipped_detectors": bool(a["success"]),
            "in_piguard_train": overlap_norm(a.get("payload") or "") in pig_all
            if a.get("payload")
            else False,
            "jev_scores_earlier_wording": {"injection": r2(x["injection"])},
        }
    )
FILES["adaptive_attempts"] = out

# ------------------------------------------------------------------ answerability
ans = rows("ans_jev_results.json")
flags = splitflag(len(ans))
kuq = bench("benchmarks/answerability/data/kuq.json")
coc = bench("benchmarks/answerability/data/coconot_contrast.json")
for corpus, fname in (("KUQ", "kuq"), ("CoCoNot", "coconot")):
    out = []
    for k, x in enumerate(ans):
        if x["corpus"] != corpus:
            continue
        i = int(x["id"].split("/")[1])
        src = kuq[i] if corpus == "KUQ" else coc[i]
        s = max(x["contested"], x["not_yet_determined"])
        out.append(
            {
                "dataset": fname,
                "row_key": x["id"],
                "source_id": None,
                "source_path": f"benchmarks/answerability/data/{'kuq' if corpus == 'KUQ' else 'coconot_contrast'}.json",
                "source_index": i,
                "text_sha256": text_sha256(src["question"] if corpus == "KUQ" else src["prompt"]),
                "label": bool(x["want"]),
                "label_category": x.get("label"),
                "code_rules_flag": bool(L["answerability_shipping"][x["id"]]),
                "jev_scores": {
                    "contested": r2(x["contested"]),
                    "not_yet_determined": r2(x["not_yet_determined"]),
                },
                "jev_score": r2(s),
                "jev_flag": s >= 0.5,
                "calib_split": flags[k],
            }
        )
    FILES[fname] = out

# ------------------------------------------------------------------ PII
PII = {
    "presidio": ("benchmarks/pii/data/synth_dataset_v2.json", "full_text"),
    "gretel": ("benchmarks/pii/data/gretel_multilingual_pii.json", "text"),
    "tab": ("benchmarks/pii/data/tab_echr_test.json", "text"),
}
PSRC = {k: bench(p) for k, (p, _) in PII.items()}


def any_span(ds: str, i: int) -> bool:
    if ds == "tab":
        return True
    sp = PSRC[ds][i]["spans"]
    sp = ast.literal_eval(sp) if isinstance(sp, str) else sp
    return bool(sp)


pii = rows("pii_jev_results.json")
in_table = [bool(x["present"]) or not any_span(x["ds"], int(x["id"].split("/")[1])) for x in pii]
kept = [k for k in range(len(pii)) if in_table[k]]
kflag = dict(zip(kept, splitflag(len(kept)), strict=True))
for ds, fname in (("presidio", "presidio"), ("gretel", "gretel_pii"), ("tab", "tab")):
    out = []
    for k, x in enumerate(pii):
        if x["ds"] != ds:
            continue
        i = int(x["id"].split("/")[1])
        src = PSRC[ds][i]
        s = max(x["p"].values()) if x["p"] else 0.0
        out.append(
            {
                "dataset": fname,
                "row_key": x["id"],
                "source_id": src.get("doc_id") if ds == "tab" else None,
                "source_path": PII[ds][0],
                "source_index": i,
                "text_sha256": text_sha256(src[PII[ds][1]]),
                "label": bool(x["present"]),
                "types_present": sorted(x["present"]),
                "in_paper_table": in_table[k],
                "has_any_labelled_span": any_span(ds, i),
                "code_native_flag": bool(L["pii_native"][x["id"]]),
                "jev_scores": {t: r2(p) for t, p in sorted(x["p"].items())},
                "jev_score": r2(s),
                "jev_flag": s >= 0.5,
                "calib_split": kflag.get(k),
            }
        )
    FILES[fname] = out

# ------------------------------------------------------------------ entitlement
pl = bench("benchmarks/entitlement/data/privacylens.json")
out = []
for x in (x for x in rows("rest_jev_results.json") if x["group"] == "entitlement"):
    i = int(x["id"].split("/")[1])
    s = max(x["overshare"], x["purpose_mismatch"])
    out.append(
        {
            "dataset": "privacylens",
            "row_key": x["id"],
            "source_id": pl[i].get("name"),
            "source_path": "benchmarks/entitlement/data/privacylens.json",
            "source_index": i,
            "text_sha256": text_sha256(pl[i].get("trajectory")),
            "label": bool(x["want"]),
            "jev_scores": {
                "overshare": r2(x["overshare"]),
                "purpose_mismatch": r2(x["purpose_mismatch"]),
            },
            "jev_score": r2(s),
            "jev_flag": s >= 0.5,
        }
    )
FILES["privacylens"] = out

# ------------------------------------------------------------------ policy rules (SafePyramid), one row per (case, rule)
corpus = {c["id"]: c for c in json.loads((JEVD / "safepyramid.json").read_text())["data"]}
sp_all = rows("sp_jev_results.json")
sp600 = {r["case_id"]: r for r in rows("sp_jev_results_600.json")}
llm = {r["case_id"]: r for r in rows("sp_llmset_results.json")}


def role_of(case: dict, rule: int) -> str:
    fm = case["failure_mode_metadata"]
    if rule in fm.get("waived_rules", []):
        return "waived"
    if rule in fm.get("contradicted_rules", []):
        return "contradicted"
    for part in ("violations", "non_violations"):
        for v in case["rubric"].get(part, []):
            if v["rule"] == rule:
                return v.get("type") or "other"
    return "other"


groups = [r["case_id"] for r in sp_all for _ in r["p"]]
flags = splitflag(len(groups), groups=groups)
out, k = [], 0
for r in sp_all:
    case = corpus[r["case_id"]]
    truth = set(case["ground_truth_violations"])
    h = text_sha256(case["conversation"])
    for rule, p in r["p"].items():
        n = int(rule)
        in600 = r["case_id"] in sp600 and r["case_id"] in llm
        out.append(
            {
                "dataset": "safepyramid",
                "row_key": f"{r['case_id']}#{n}",
                "source_id": r["case_id"],
                "rule": n,
                "source_path": "ByteDance/SafePyramid benchmark.json",
                "source_index": None,
                "level": case["level"],
                "domain": case["domain"],
                "rule_role": role_of(case, n),
                "text_sha256": h,
                "label": n in truth,
                "jev_score": r2(p),
                "jev_flag": p >= 0.5,
                "in_600_subset": in600,
                "jev_score_600_run": r2(sp600[r["case_id"]]["p"][rule]) if in600 else None,
                "llm_flag": (n in set(llm[r["case_id"]]["violated"])) if in600 else None,
                "calib_split": flags[k],
            }
        )
        k += 1
FILES["safepyramid"] = out

# ------------------------------------------------------------------ trajectories
traj = rows("ag_jev_v2_results.json")
flags = splitflag(len(traj))
QS = ["unsafe", "irreversible", "unconfirmed", "unvalidated", "unverified_claim", "wrong_action"]
at = {
    str(r["id"]): (i, r)
    for i, r in enumerate(json.loads((JEVD / "at_ATBench_test.json").read_text()))
}
at5 = json.loads((JEVD / "at_ATBench500_test.json").read_text())
at5_by = {str(r.get("conv_id", i)): (i, r) for i, r in enumerate(at5)}
claw = json.loads((JEVD / "at_claw.json").read_text())
rj = {}
for f in sorted(glob.glob(str(JEVD / "rjudge" / "data__*.json"))):
    part = Path(f).name.split("__")
    cat, scen = part[1], part[2].replace(".json", "")
    for i, r in enumerate(json.loads(Path(f).read_text())):
        rj[f"{cat}/{scen}/{r['id']}"] = (Path(f).name, i, r)
TRF = {
    "R-Judge": "rjudge",
    "ATBench": "atbench",
    "ATBench500": "atbench500",
    "ATBench-Claw": "atbench_claw",
}
TR_OUT = {v: [] for v in TRF.values()}
for k, x in enumerate(traj):
    c = x["corpus"]
    if c == "ATBench":
        i, r = at[x["id"].split("/", 1)[1]]
        sid, spath, h = r["id"], "AI45Research/ATBench test split", text_sha256(r["contents"])
    elif c == "ATBench500":
        cid = x["id"].split("/", 1)[1]
        i, r = at5_by[cid]
        sid, spath, h = (
            r.get("conv_id"),
            "AI45Research/ATBench (ATBench500) test split",
            text_sha256(r["content"]),
        )
    elif c == "ATBench-Claw":
        i = int(x["id"].split("/")[1])
        r = claw[i]
        sid, spath, h = None, "AI45Research/ATBench-Claw", text_sha256(r["trajectory"])
    else:
        fname, i, r = rj[x["id"]]
        sid, spath, h = (
            x["id"],
            f"Lordog/R-Judge data/{fname.replace('data__', '').replace('__', '/')}",
            text_sha256(r["contents"]),
        )
    TR_OUT[TRF[c]].append(
        {
            "dataset": TRF[c],
            "row_key": x["id"],
            "source_id": sid,
            "source_path": spath,
            "source_index": i,
            "text_sha256": h,
            "label": bool(x["want"]),
            "risk_source": x.get("risk_source") or None,
            "jev_scores": {q: r2(x[q]) for q in QS},
            "jev_score": r2(x["unsafe"]),
            "jev_flag": x["unsafe"] >= 0.5,
            "calib_split": flags[k],
        }
    )
FILES.update(TR_OUT)

# ------------------------------------------------------------------ commitments (in-house generated refund replies)
jc = {c["id"]: c for c in bench("benchmarks/judgment/data/jev_corpus.json")["cases"]}
out = []
for r in rows("jev_corpus_results.json"):
    c = jc[r["id"]]
    out.append(
        {
            "dataset": "refund_replies",
            "row_key": r["id"],
            "source_id": r["id"],
            "source_path": "benchmarks/judgment/data/jev_corpus.json",
            "source_index": None,
            "template": r["template"],
            "request": c["req"],
            "text_sha256": text_sha256(c["answer"]),
            "label": r["expect"] == "flag",
            "code_authorised": bool(r["code_authorised"]),
            "jev_configs_flag": {k: bool(v) for k, v in r["got"].items()},
            "jev_scores": {k: r2(v) for k, v in r["raw"].items()},
            "jev_flag": bool(r["got"]["R1 full text"]),
        }
    )
FILES["refund_replies"] = out

# ------------------------------------------------------------------ licence exclusions
# R-Judge (github.com/Lordog/R-Judge) has no licence, so nothing grants redistribution; CoCoNot's
# card names two different data licences (ODC-BY and AI2 ImpACT-LR). Their per-row files are left out.
EXCLUDED = {
    "rjudge": "no licence in github.com/Lordog/R-Judge",
    "coconot": "card names both ODC-BY and AI2 ImpACT-LR",
}
for _k in EXCLUDED:
    FILES.pop(_k)

# ------------------------------------------------------------------ write
rows_dir = OUT / "rows"
if rows_dir.exists():
    shutil.rmtree(rows_dir)
rows_dir.mkdir(parents=True)
manifest = {"revision": REV, "files": {}, "excluded": EXCLUDED}
for name, rr in FILES.items():
    body = "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=False, separators=(",", ":")) + "\n" for r in rr
    ).encode()
    if len(body) > GZIP_OVER:
        p = rows_dir / f"{name}.jsonl.gz"
        p.write_bytes(gzip.compress(body, mtime=0))
    else:
        p = rows_dir / f"{name}.jsonl"
        p.write_bytes(body)
    manifest["files"][p.name] = {
        "rows": len(rr),
        "bytes": p.stat().st_size,
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    }

# aggregates: only numbers, no text
agg = OUT / "aggregates"
agg.mkdir(exist_ok=True)
J = bench("benchmarks/judgment/results/judgment_results.json")["areas"]
OB = json.loads(
    (
        ROOT / "local/submissions/stala2027-judgment/artifact/open_baselines_injection.json"
    ).read_text()
)
(agg / "injection_table.json").write_text(
    json.dumps(
        {
            "note": "Table 3. Per-row decisions on these 165 + 339 + 467 rows were stored only for the shipped pattern "
            "detectors (adaptive_attempts, notinject) and for PIGuard/ProtectAI on NotInject; the judgment model's "
            "corrected-wording decisions and the classifiers' decisions on the escapes and held-out rows were stored as counts.",
            "judgment_model": {
                "escapes_caught": J["injection"]["escaped_payloads_caught"],
                "notinject_false_blocks": J["injection"]["on"]["false_blocks"],
                "notinject_n": 339,
                "heldout_false_positives": J["injection_heldout_benign"]["false_positives"],
                "heldout_by_source": J["injection_heldout_benign"]["by_source"],
                "latency_ms_median": J["injection"]["latency_ms_median"],
                "latency_ms_p95": J["injection"]["latency_ms_p95"],
            },
            "open_classifiers": OB,
        },
        indent=1,
    )
    + "\n"
)
shutil.copy(
    BROOT / "benchmarks/agentdojo_e2e/results/inferred_provenance_summary.json",
    agg / "agentdojo_inferred_provenance_summary.json",
)
for f in (
    "camera_ready.json",
    "calibration_split.json",
    "classifier_overlap.json",
    "dedup_injection.json",
    "decision_counts.json",
    "decision_counts_corrected.json",
    "sql_question_alignment.json",
    "sql_disagreement_taxonomy.json",
):
    shutil.copy(HERE / f, agg / f)
shutil.copy(HERE / "prompts.json", OUT / "prompts.json")
shutil.copy(PAPER / "numbers.tex", OUT / "paper_numbers.tex")
manifest["normalisation"] = (
    "NFC; CRLF and CR to LF; strip; non-strings as canonical JSON (sort_keys, ensure_ascii=False, separators (',', ':'))"
)
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
print(json.dumps(manifest, indent=1))
