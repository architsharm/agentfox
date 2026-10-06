"""Scores `src/agentfox/evaluation/redteam.py`'s `NativeRedTeamRunner` — the
red-team campaign runner itself, not the underlying detectors it calls (those
are separately benchmarked: `benchmarks/REPORT.md`, `benchmarks/pii/`,
`benchmarks/action_safety/`).

    uv run python benchmarks/redteam/run_redteam_benchmark.py

**A different kind of benchmark from most others in this repo, and that
difference is the point.** `benchmarks/REPORT.md` etc. score whether a
detector correctly classifies text against a public dataset's own labels.
This benchmark instead asks: does the red-team *runner* actually reach every
layer of enforcement it claims to exercise? Before this round, every
built-in probe was `kind="content"`, which only ever calls
`Enforcer.check_content()` — and `check_content()` never passes `arguments`/
`tool_key` to `evaluate()`, so capability/constraint checks, the
action-assurance/SQLi-scope backstop, and composed-privilege-escalation
(F3.8) were **structurally unreachable by any red-team probe**, regardless of
how well those layers work in isolation. `kind="tool_call"`/`"scenario"`
probes (added this round) close that. This benchmark's job is to prove the
wiring is real: every one of `BUILTIN_PROBES` run through the actual
`run_campaign()` path, against a really-seeded agent, with real policy
enforcement — not a mock of any of it.

It also has a genuine recall *and* precision claim, which no prior version of
this suite could produce at all: every probe used to be an attack
(`expect_blocked=True`), so a campaign could only ever report how much it
caught, never how much legitimate traffic it wrongly stopped.
`benign_control` probes (`expect_blocked=False`) close that gap too.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="redteam_bench_")
    os.environ["NOMETRIA_DATABASE_URL"] = f"sqlite:///{tmpdir}/bench.db"
    os.environ["NOMETRIA_EVIDENCE_DIR"] = f"{tmpdir}/evidence"
    os.environ["NOMETRIA_AUDIT_SIGNING_KEY"] = "bench-key"
    os.environ["NOMETRIA_ALLOW_EGRESS"] = "false"

    from agentfox.core import db
    from agentfox.core.config import reset_settings_cache
    from agentfox.evaluation.redteam import BUILTIN_PROBES, run_campaign
    from agentfox.fixtures.seed import seed as run_seed
    from agentfox.policy import set_mode

    reset_settings_cache()
    db.reset_engine()
    db.init_db()

    attacks = [p for p in BUILTIN_PROBES if p.expect_blocked]
    benign = [p for p in BUILTIN_PROBES if not p.expect_blocked]
    print(
        f"{len(BUILTIN_PROBES)} built-in probes: {len(attacks)} attacks, {len(benign)} benign controls"
    )
    by_kind: dict[str, int] = {}
    for p in BUILTIN_PROBES:
        by_kind[p.kind] = by_kind.get(p.kind, 0) + 1
    print(f"by kind: {by_kind}")

    with db.session_scope() as session:
        run_seed(session)
        set_mode(session, "baseline", "enforce")
        set_mode(session, "tool-containment", "enforce")

        # Every registered agent, not just one — the runner's own doc claims it
        # exercises "the deployed configuration", so this checks that holds across
        # every seed agent's actual grants, not just a single hand-picked one.
        from agentfox.core.models import Agent

        agent_slugs = [a.slug for a in session.query(Agent).all()]
        print(f"scoring against agents: {agent_slugs}")

        campaigns = []
        for slug in agent_slugs:
            campaign = run_campaign(session, slug, name=f"benchmark-{slug}")
            campaigns.append((slug, campaign))

    results = {
        "probes": {
            "total": len(BUILTIN_PROBES),
            "attacks": len(attacks),
            "benign_controls": len(benign),
            "by_kind": by_kind,
        },
        "agents": {},
    }
    for slug, campaign in campaigns:
        s = campaign.summary_json
        results["agents"][slug] = {
            "recall": s["recall"],
            "precision": s["precision"],
            "attacks_run": s["attacks_run"],
            "attacks_blocked": s["attacks_blocked"],
            "attacks_succeeded": s["attacks_succeeded"],
            "benign_probes_run": s["benign_probes_run"],
            "benign_false_positives": s["benign_false_positives"],
            "by_category": s["by_category"],
            "critical_breaches": s["critical_breaches"],
        }
        print(
            f"  {slug:16s} recall={s['recall']:.0%}  precision={s['precision']:.0%}  "
            f"({s['attacks_blocked']}/{s['attacks_run']} attacks, "
            f"{s['benign_false_positives']}/{s['benign_probes_run']} benign FPs)"
        )

    out_path = RESULTS_DIR / "redteam_summary.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
