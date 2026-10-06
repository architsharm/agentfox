"""Scores the **adaptive** red-team campaign engine (`evaluation/adaptive.py`).

    uv run python benchmarks/redteam/run_adaptive_redteam_benchmark.py

`run_redteam_benchmark.py` next door asks whether the runner's *wiring* is real —
does a probe reach every enforcement layer it claims to. This one asks the
question that wiring makes possible and that a static suite structurally cannot
answer:

    Given the same known attack classes, what does it take to get them through
    THIS deployment, and did that get easier since the last campaign?

**Three things are measured, and none of them is a robustness claim.**

1. *Escape rate by mutation class.* Which class of evasion — encoding,
   obfuscation, argument shape, provenance, tool scope — actually defeats this
   configuration. A class that works is named, not averaged into a score.
2. *Escape rate by agent.* The same library against three seed agents with
   genuinely different grants, ceilings and risk tiers, so the result is a
   property of each deployment rather than of the library.
3. *Posture delta.* A capability ceiling is deliberately removed between two
   campaigns for one agent, and the benchmark records whether the campaign says
   so. This is the headline the feature exists to produce, so it is measured
   rather than asserted.

**Honesty conventions, same as `benchmarks/containment/`.** Negative controls are
scored as failures when wrongly blocked. Every escape is written to the results
file with the payload or arguments that produced it, so a reader who does not
trust the aggregate can re-run the exact thing that got through. The scope
statement carried in every campaign summary is reproduced in the output. And the
findings this run surfaced about our own product are in
`benchmarks/redteam/README.md` rather than only in the JSON.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"
BUDGET = 4
SEED = 1337


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="adaptive_redteam_bench_")
    os.environ["NOMETRIA_DATABASE_URL"] = f"sqlite:///{tmpdir}/bench.db"
    os.environ["NOMETRIA_EVIDENCE_DIR"] = f"{tmpdir}/evidence"
    os.environ["NOMETRIA_AUDIT_SIGNING_KEY"] = "bench-key"
    os.environ["NOMETRIA_ALLOW_EGRESS"] = "false"

    from agentfox.core import db
    from agentfox.core.config import reset_settings_cache
    from agentfox.core.models import Agent, Capability, Identity
    from agentfox.evaluation.adaptive import OPERATORS, SCOPE_STATEMENT, mutation_classes
    from agentfox.evaluation.redteam import BUILTIN_PROBES, run_campaign
    from agentfox.fixtures.seed import seed as run_seed
    from agentfox.policy import set_mode

    reset_settings_cache()
    db.reset_engine()
    db.init_db()

    print(f"{len(OPERATORS)} operators across {len(mutation_classes())} mutation classes")
    print(
        f"seed probes: {len(BUILTIN_PROBES)} static + deployment-derived, "
        f"budget={BUDGET}, seed={SEED}"
    )

    results: dict[str, Any] = {
        "benchmark": "adaptive red-team campaign engine",
        "question": (
            "Given the same known attack classes, what does it take to get them through "
            "this deployment, and did that get easier since the last campaign?"
        ),
        "what_this_measures": SCOPE_STATEMENT,
        "budget": BUDGET,
        "seed": SEED,
        "operators": [
            {"key": op.key, "class": op.mutation_class, "kinds": list(op.kinds)} for op in OPERATORS
        ],
        "agents": {},
        "by_mutation_class": {},
        "by_semantics": {},
        "posture_regression_check": {},
    }

    with db.session_scope() as session:
        run_seed(session)
        set_mode(session, "baseline", "enforce")
        set_mode(session, "tool-containment", "enforce")
        slugs = sorted(a.slug for a in session.query(Agent).all())
        print(f"agents: {slugs}\n")

        totals: dict[str, dict[str, int]] = {}
        sem_totals: dict[str, dict[str, int]] = {}
        for slug in slugs:
            static = run_campaign(session, slug, name=f"static-{slug}")
            static_escapes = {p["key"] for p in static.summary_json["probes"] if p["succeeded"]}
            campaign = run_campaign(
                session,
                slug,
                name=f"adaptive-{slug}",
                adaptive=True,
                budget=BUDGET,
                seed=SEED,
            )
            summary = campaign.summary_json
            adaptive = summary["adaptive"]
            found_by_mutation = sorted(set(adaptive["escaping_probes"]) - static_escapes)

            for cls, bucket in adaptive["escape_rate_by_mutation_class"].items():
                agg = totals.setdefault(cls, {"attempts": 0, "escapes": 0})
                agg["attempts"] += bucket["attempts"]
                agg["escapes"] += bucket["escapes"]
            for sem, bucket in adaptive["escape_rate_by_semantics"].items():
                agg = sem_totals.setdefault(sem, {"attempts": 0, "escapes": 0})
                agg["attempts"] += bucket["attempts"]
                agg["escapes"] += bucket["escapes"]

            results["agents"][slug] = {
                "risk_tier": adaptive["deployment_profile"]["risk_tier"],
                "static_recall": static.summary_json["recall"],
                "adaptive_recall": summary["recall"],
                "precision": summary["precision"],
                "benign_false_positives": summary["benign_false_positives"],
                "seed_probes": adaptive["seed_probes"],
                "attempts_used": adaptive["attempts_used"],
                "static_escapes": sorted(static_escapes),
                "adaptive_escapes": adaptive["escaping_probes"],
                "found_only_by_mutation": found_by_mutation,
                "mutation_classes_that_worked": adaptive["mutation_classes_that_worked"],
                "by_target_class": adaptive["by_target_class"],
                "deployment_probes": adaptive["deployment_probes"],
                "bound_policy_modes": adaptive["bound_policy_modes"],
                "escapes": adaptive["escapes"],
            }
            print(
                f"  {slug:16s} static {len(static_escapes):2d} escapes -> adaptive "
                f"{len(adaptive['escaping_probes']):2d} escapes "
                f"(+{len(found_by_mutation)} found only by mutation) in "
                f"{adaptive['attempts_used']:3d} attempts; "
                f"classes that worked: "
                f"{', '.join(adaptive['mutation_classes_that_worked']) or 'none'}; "
                f"benign FPs {summary['benign_false_positives']}/{summary['benign_probes_run']}"
            )

        results["by_mutation_class"] = {
            cls: {
                **agg,
                "escape_rate": round(agg["escapes"] / agg["attempts"], 4)
                if agg["attempts"]
                else 0.0,
            }
            for cls, agg in sorted(totals.items())
        }
        # Split by operator semantics, the distinction borrowed from
        # `benchmarks/adaptive/operators.py`: a `requires_decode` escape proves the
        # detector missed it, not that the agent would have acted on it. Reported
        # separately so the easy ones are never banked quietly.
        results["by_semantics"] = {
            sem: {
                **agg,
                "escape_rate": round(agg["escapes"] / agg["attempts"], 4)
                if agg["attempts"]
                else 0.0,
            }
            for sem, agg in sorted(sem_totals.items())
        }

        # -- posture delta, measured rather than asserted -------------------
        # A real configuration regression: someone removes the argument ceiling
        # from a capability grant. The prompt is byte-identical in both campaigns,
        # which is exactly why a static suite cannot see this and why the feature
        # is framed as configuration regression testing.
        probes = ["capability.constraint_violation"]
        kwargs = dict(adaptive=True, budget=1, probes=probes, include_deployment_probes=False)
        tight = run_campaign(session, "support-triage", name="posture-tight", **kwargs)
        # Scoped to support-triage's own identity: every agent has its own grant for
        # the synthetic tool, and widening all three would change what the other
        # agents' campaigns measure.
        agent = session.query(Agent).filter(Agent.slug == "support-triage").one()
        identity = session.query(Identity).filter(Identity.agent_id == agent.id).one()
        cap = (
            session.query(Capability)
            .filter(
                Capability.identity_id == identity.id,
                Capability.tool_key == "redteam.sim.issue_refund",
            )
            .one()
        )
        original = dict(cap.constraints_json or {})
        cap.constraints_json = {}
        session.flush()
        widened = run_campaign(session, "support-triage", name="posture-widened", **kwargs)
        cap.constraints_json = original
        session.flush()
        restored = run_campaign(session, "support-triage", name="posture-restored", **kwargs)

        results["posture_regression_check"] = {
            "scenario": (
                "The $1,000 argument ceiling on a capability grant is removed between "
                "campaign 1 and campaign 2, then restored for campaign 3. The probe "
                "payload is identical in all three."
            ),
            "campaign_1_escapes": tight.summary_json["adaptive"]["escaping_probes"],
            "campaign_1_direction": tight.summary_json["posture"]["direction"],
            "campaign_2_escapes": widened.summary_json["adaptive"]["escaping_probes"],
            "campaign_2_direction": widened.summary_json["posture"]["direction"],
            "campaign_2_headline": widened.summary_json["headline"],
            "campaign_3_direction": restored.summary_json["posture"]["direction"],
            "campaign_3_resolved": restored.summary_json["posture"]["resolved_escapes"],
        }

    print("\nescape rate by mutation class (all agents, mutated attempts only):")
    for cls, agg in results["by_mutation_class"].items():
        if agg["attempts"]:
            print(
                f"  {cls:16s} {agg['escapes']:3d}/{agg['attempts']:3d} = {agg['escape_rate']:.0%}"
            )
    print("\nescape rate by operator semantics:")
    for sem, agg in results["by_semantics"].items():
        if agg["attempts"]:
            print(
                f"  {sem:16s} {agg['escapes']:3d}/{agg['attempts']:3d} = {agg['escape_rate']:.0%}"
            )
    print("\nposture delta:")
    for key in ("campaign_1_direction", "campaign_2_direction", "campaign_3_direction"):
        print(f"  {key:24s} {results['posture_regression_check'][key]}")

    out_path = RESULTS_DIR / "adaptive_redteam_summary.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_path}")
    print(f"\n{SCOPE_STATEMENT}")


if __name__ == "__main__":
    main()
