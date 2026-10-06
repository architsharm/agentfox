"""Tier C — tool parameter exploitation / data over-privilege.

    uv run python benchmarks/agent_security/tier_c_tool_params.py

The attack shape: the tool itself is unremarkable and the agent's capability grant
for it is genuinely valid — the danger is in an *ordinary-named* argument value.
`look_up_order(order_id="*")` looks nothing like the SQL/shell/URL fields
`src/agentfox/capabilities/detection/actions.py` used to check by key name alone
(`_SQL_KEYS`/`_SHELL_KEYS`/`_URL_KEYS`); a field called `order_id` was never on
any of those lists, so a wildcard or an injected fragment there went straight
through P9 Action Assurance's dispatch. That gap is real — confirmed by reading
the code before writing this, not assumed — and this benchmark exists on the far
side of closing it, not the near side: `analyse_scope()`
(`src/agentfox/capabilities/detection/actions.py`) now runs on every string argument
regardless of key name.

LLM Guard has no equivalent axis to measure here at all: it scans free text, not
structured tool-call arguments, so it cannot see `{"order_id": "*"}` as anything
but an opaque JSON blob with no injection-shaped text in it. This tier is reported
as AgentFox-only, not "AgentFox N%, LLM Guard 0%" — the honest framing the user's
own thesis asked for is "cannot participate", not a manufactured zero.

10 cases: 5 real over-privilege/injection shapes across 3 attack families
(wildcard scope expansion, SQL injection in an unnamed field, path traversal in
an unnamed field), 5 negative controls — ordinary lookups and free text that
happen to share vocabulary with the attacks (the word "all" in a sentence, a
filename with dots) — so a detector that just pattern-matches loosely doesn't
get credit it didn't earn, same discipline as Tier B's benign set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from _util import wipe_db

from agentfox.core import db
from agentfox.core.config import get_settings, reset_settings_cache
from agentfox.fixtures.seed import seed
from agentfox.runtime.enforcement import Enforcer

DATA_PATH = Path(__file__).parent / "data" / "tier_c_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"

_INTERVENED = {"block", "escalate", "redact"}


def load_cases() -> list[dict]:
    return json.loads(DATA_PATH.read_text())


def run_case(enforcer: Enforcer, case: dict) -> dict:
    # See tier_b_indirect_injection.py's identical comment: Enforcer.ledger() is a
    # request-scoped budget that persists across calls on one Enforcer instance by
    # design (P3-13) — reset per case here since these are independent benchmark
    # cases, not surfaces of one request. Tier C's blocking mechanism (P9 Action
    # Assurance) is deterministic argument analysis, not detector-pipeline timing,
    # so this was lower-risk than Tier B's, but it's the same correctness
    # requirement and cheap to apply consistently.
    enforcer.reset_ledger()
    result = enforcer.guard_tool_call(
        agent_slug="support-triage", tool_key=case["tool_key"], arguments=case["arguments"]
    )
    intervened = result.effective_verdict in _INTERVENED
    correct = intervened == bool(case["label"])
    return {
        "id": case["id"],
        "attack_family": case["attack_family"],
        "narrative": case["narrative"],
        "label": case["label"],
        "effective_verdict": result.effective_verdict,
        "intervened": intervened,
        "correct": correct,
        "rules_fired": [r.get("rule_id") for r in result.rules_fired],
        "capability_granted": result.taint.get("capability", {}).get("granted"),
        "degraded": list(result.degraded),
    }


def main() -> None:
    cases = load_cases()
    db_path = RESULTS_DIR / "tier_c.db"
    wipe_db(db_path)
    os.environ["NOMETRIA_DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ.setdefault("NOMETRIA_AUDIT_SIGNING_KEY", "benchmark-key")
    os.environ.setdefault("NOMETRIA_ALLOW_EGRESS", "false")
    reset_settings_cache()
    get_settings()
    db.init_db()

    results = []
    with db.session_scope() as session:
        seed(session)
        # support-triage already has kb.search/crm.lookup/tickets.* granted by the
        # shipped seed data — the capability check genuinely passes for every case
        # here, so a block only ever comes from the argument-value analysis, never
        # from a missing grant. Confirmed per-case via `capability_granted` below.
        enforcer = Enforcer(session)
        for case in cases:
            results.append(run_case(enforcer, case))
    wipe_db(db_path)

    n_correct = sum(1 for r in results if r["correct"])
    all_granted = all(r["capability_granted"] for r in results)
    summary = {
        "tier": "C — tool parameter exploitation / data over-privilege",
        "methodology": (
            "Real Enforcer.guard_tool_call against support-triage's genuinely "
            "granted capabilities (kb.search, crm.lookup, tickets.*) — every case "
            "passes the capability check, so any block comes from argument-value "
            "analysis alone, not from a missing grant. LLM Guard has no tool-call "
            "argument concept and cannot participate in this tier at all."
        ),
        "n_scenarios": len(results),
        "n_correct": n_correct,
        "accuracy": round(n_correct / len(results), 4),
        "all_capability_checks_passed": all_granted,
        "scenarios": results,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "tier_c_results.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
