"""Replay a third-party labelled prompt-injection corpus through our detectors.

    uv run python -m benchmarks.toolkit_corpus.run_prompt_injection_corpus

**Data.** `data/prompt_injection/injection-smoke.jsonl` is the 280-row synthetic smoke corpus
(110 attack rows, 170 benign rows) published with Microsoft's MIT-licensed agent governance
toolkit, copied unchanged at upstream commit c767f83 (licence in `data/LICENSE`, provenance in
`README.md`). Its generator's hash check is repeated here before anything is scored, so a
modified copy cannot produce a number. Nothing from that repository is executed; the corpus is
read as data.

**Arms.** Two, because "our detector" means two different things depending on who is asking:

* `injection_heuristic` — `injection.heuristic` alone, through `DetectorPipeline`. The closest
  like-for-like with the upstream rules-only baseline: one deterministic rules detector, default
  configuration, no models.
* `default_stack` — the real `Enforcer.check_content` path with the shipped default detector
  list and the shipped policy packs, the same call `/v1/guard` makes. Each row is checked on the
  surface its `source_type` names (a user turn is `input`; a document, RAG chunk or ticket is
  `retrieved`; a tool result is `tool_result`; a memory record is `memory_write`), with the
  matching taint source. Reported twice: whether any `INJECTION.*` entity was raised (detection),
  and whether the verdict held the content (`block` or `escalate`, which is what a caller sees).

Flagged means "raised at least one `INJECTION.*` entity"; recall is over the 110 attack rows and
the false-positive rate over the 170 benign rows. Nothing was tuned to this corpus: the
detectors are exactly what `main` ships.

Fully offline and deterministic apart from the latency figures.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Bind the throwaway database before anything reads settings (see containment/ for why).
DB_PATH = Path(tempfile.gettempdir()) / "agentfox_toolkit_corpus_pi.db"
os.environ["AGENTFOX_DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ.setdefault("AGENTFOX_CONFIG", "none")
os.environ.pop("AGENTFOX_ENABLED_DETECTORS", None)

from agentfox.capabilities.detection import (  # noqa: E402
    DetectionContext,
    DetectorPipeline,
    get_detector,
)
from agentfox.core import db  # noqa: E402
from agentfox.core.config import get_settings, reset_settings_cache  # noqa: E402
from agentfox.fixtures.seed import seed  # noqa: E402
from agentfox.runtime.enforcement import Enforcer  # noqa: E402
from benchmarks._common import wipe_db  # noqa: E402

HERE = Path(__file__).parent
CORPUS = HERE / "data" / "prompt_injection" / "injection-smoke.jsonl"
MANIFEST = HERE / "data" / "prompt_injection" / "manifest-smoke.json"
UPSTREAM_BASELINE = HERE / "data" / "prompt_injection" / "rules-baseline-smoke-summary.json"
RESULTS = HERE / "results" / "prompt_injection_corpus.json"

AGENT = "support-triage"
HELD = {"block", "escalate"}

#: source_type -> (surface, taint source). The surface decides which detectors and rules
#: apply; the taint source is what a real integration would declare for that content.
SURFACE_FOR_SOURCE = {
    "user": ("input", "user"),
    "document": ("retrieved", "retrieved"),
    "rag_chunk": ("retrieved", "retrieved"),
    "ticket": ("retrieved", "retrieved"),
    "tool_result": ("tool_result", "tool_result"),
    "memory": ("memory_write", "memory"),
}

GROUPINGS = ("attack_class", "bypass_class", "source_type", "benign_subclass", "split")


def wilson(successes: int, total: int, z: float = 1.959964) -> dict[str, Any]:
    if total == 0:
        return {"estimate": None, "lower": None, "upper": None, "successes": 0, "total": 0}
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return {
        "estimate": round(p, 4),
        "lower": round(max(0.0, centre - half), 4),
        "upper": round(min(1.0, centre + half), 4),
        "successes": successes,
        "total": total,
    }


def load_corpus() -> list[dict[str, Any]]:
    raw = CORPUS.read_bytes()
    expected = json.loads(MANIFEST.read_text())["output_sha256"]
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise SystemExit(f"corpus hash {actual} does not match the upstream manifest {expected}")
    return [json.loads(line) for line in raw.decode().splitlines() if line.strip()]


def is_attack(row: dict[str, Any]) -> bool:
    return row["attack_class"] != "benign"


def injection_entities(entity_types: list[str]) -> list[str]:
    return sorted({e for e in entity_types if str(e).startswith("INJECTION")})


def latency(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


def tally(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    attacks = [r for r in rows if r["attack"]]
    benign = [r for r in rows if not r["attack"]]
    caught = sum(1 for r in attacks if r[key])
    flagged = sum(1 for r in benign if r[key])
    return {
        "attacks": len(attacks),
        "attacks_caught": caught,
        "attack_recall": wilson(caught, len(attacks)),
        "benign": len(benign),
        "benign_flagged": flagged,
        "benign_fp_rate": wilson(flagged, len(benign)),
        "fp_per_1k_benign": round(1000 * flagged / len(benign), 2) if benign else None,
    }


def breakdowns(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for grouping in GROUPINGS:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[r[grouping]].append(r)
        out[grouping] = {name: tally(members, key) for name, members in sorted(groups.items())}
    return out


def fresh_db() -> None:
    wipe_db(DB_PATH)
    db.init_db()
    with db.session_scope() as session:
        seed(session)


def main() -> None:
    corpus = load_corpus()
    reset_settings_cache()
    detectors = list(get_settings().enabled_detectors)
    fresh_db()

    heuristic = get_detector("injection.heuristic")
    assert heuristic is not None
    heuristic_only = DetectorPipeline(detectors=[heuristic])

    scored: list[dict[str, Any]] = []
    heuristic_ms: list[float] = []
    stack_ms: list[float] = []
    with db.session_scope() as session:
        enforcer = Enforcer(session)
        # One warm-up call so lazy imports do not land on the first row's latency.
        enforcer.check_content(agent_slug=AGENT, content="warm up", persist=False)
        heuristic_only.run("warm up", DetectionContext(surface="input"))
        for row in corpus:
            surface, taint = SURFACE_FOR_SOURCE[row["source_type"]]
            started = time.perf_counter()
            h = heuristic_only.run(row["text"], DetectionContext(surface=surface))
            heuristic_ms.append((time.perf_counter() - started) * 1000)
            h_entities = injection_entities([d.entity_type for d in h.detections])

            started = time.perf_counter()
            result = enforcer.check_content(
                agent_slug=AGENT,
                content=row["text"],
                surface=surface,
                taint_source=taint,
                persist=False,
            )
            stack_ms.append((time.perf_counter() - started) * 1000)
            entities = list(result.get("entities") or [])
            verdict = result.get("effective_verdict", "allow")
            scored.append(
                {
                    "id": row["id"],
                    "attack": is_attack(row),
                    **{g: row[g] for g in GROUPINGS},
                    "expected_action": row["expected_action"],
                    "surface": surface,
                    "heuristic_flagged": bool(h_entities),
                    "heuristic_entities": h_entities,
                    "stack_flagged": bool(injection_entities(entities)),
                    "stack_entities": sorted(entities),
                    "stack_verdict": verdict,
                    "stack_held": verdict in HELD,
                    "rules_fired": sorted(
                        {r.get("rule_id") for r in result.get("rules_fired") or []} - {None}
                    ),
                }
            )
    wipe_db(DB_PATH)

    upstream = json.loads(UPSTREAM_BASELINE.read_text())
    benign_held = [r for r in scored if not r["attack"] and r["stack_held"]]
    benign_entity_types = Counter(
        e for r in scored if not r["attack"] and r["stack_held"] for e in r["stack_entities"]
    )
    summary = {
        "benchmark": "third-party prompt-injection smoke corpus, replayed through our detectors",
        "corpus": {
            "path": str(CORPUS.relative_to(HERE.parent.parent)),
            "rows": len(corpus),
            "sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
            "upstream_commit": "c767f83",
            "licence": "MIT (data/LICENSE)",
        },
        "active_detectors": detectors,
        "agent": AGENT,
        "surface_for_source_type": {k: list(v) for k, v in SURFACE_FOR_SOURCE.items()},
        "tuned_to_corpus": False,
        "headline": {
            "heuristic_attacks_caught": (
                f"{sum(r['heuristic_flagged'] for r in scored if r['attack'])}"
                f"/{sum(r['attack'] for r in scored)}"
            ),
            "heuristic_benign_flagged": (
                f"{sum(r['heuristic_flagged'] for r in scored if not r['attack'])}"
                f"/{sum(not r['attack'] for r in scored)}"
            ),
            "stack_attacks_caught": (
                f"{sum(r['stack_flagged'] for r in scored if r['attack'])}"
                f"/{sum(r['attack'] for r in scored)}"
            ),
            "stack_benign_flagged": (
                f"{sum(r['stack_flagged'] for r in scored if not r['attack'])}"
                f"/{sum(not r['attack'] for r in scored)}"
            ),
            "stack_attacks_held": (
                f"{sum(r['stack_held'] for r in scored if r['attack'])}"
                f"/{sum(r['attack'] for r in scored)}"
            ),
            "stack_benign_held": f"{len(benign_held)}/{sum(not r['attack'] for r in scored)}",
        },
        "arms": {
            "injection_heuristic": {
                "overall": tally(scored, "heuristic_flagged"),
                "latency": latency(heuristic_ms),
                "by": breakdowns(scored, "heuristic_flagged"),
            },
            "default_stack_detection": {
                "overall": tally(scored, "stack_flagged"),
                "latency": latency(stack_ms),
                "by": breakdowns(scored, "stack_flagged"),
            },
            "default_stack_held": {
                "overall": tally(scored, "stack_held"),
                "by": breakdowns(scored, "stack_held"),
                "benign_held_entity_types": dict(sorted(benign_entity_types.items())),
            },
        },
        "verdict_by_expected_action": {
            expected: dict(
                sorted(
                    Counter(
                        r["stack_verdict"] for r in scored if r["expected_action"] == expected
                    ).items()
                )
            )
            for expected in sorted({r["expected_action"] for r in scored})
        },
        "upstream_published_baseline": {
            "source": "data/prompt_injection/rules-baseline-smoke-summary.json",
            "detector": upstream["detector"],
            "overall": upstream["overall"],
            "by_attack_class": {
                k: {"attacks": v["attacks"], "attacks_caught": v["attacks_caught"]}
                for k, v in upstream["by_attack_class"].items()
                if v["attacks"]
            },
            "note": "Quoted from the upstream artifact, not re-run here.",
        },
        "rows": scored,
    }
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["headline"], indent=2))
    for arm in ("injection_heuristic", "default_stack_detection", "default_stack_held"):
        overall = summary["arms"][arm]["overall"]
        print(
            f"{arm:26s} recall {overall['attacks_caught']}/{overall['attacks']}"
            f"  fp {overall['benign_flagged']}/{overall['benign']}"
        )


if __name__ == "__main__":
    main()
