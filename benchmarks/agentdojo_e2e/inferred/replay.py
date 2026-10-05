"""Replay executed AgentDojo traces through AgentFox's real enforcement path.

    uv run python benchmarks/agentdojo_e2e/inferred/replay.py traces_v1.2.2.json out.json
    GRANT_MODE=tiered uv run python benchmarks/agentdojo_e2e/inferred/replay.py \
        traces_v1.2.2.json out_tiered.json inferred,inferred_arg

Conditions (crossed with detectors on/off):
  oracle    -- provenance declared from the benchmark label (the repo's original method):
               benign/user-task args = "user", injection-task args = "tool_result".
  inferred  -- NO labels. One TaintTracker per trace: the user prompt is marked "user",
               every tool output is marked "tool_result" after it is returned, and each
               call's argument provenance is inferred by the shipped tracker.
  cap_only  -- ablation: provenance disabled entirely (no content marked), leaving only
               grants (default-deny), impact tiers and the intent rule.

All calls in a trace receive the SAME declared intent (the user's prompt), so intent
cannot leak the label.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

SCRATCH = Path(tempfile.gettempdir())
DB_PATH = SCRATCH / os.environ.get("REPLAY_DB", "agentfox_agentdojo_inferred.db")
os.environ["NOMETRIA_DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ.setdefault("NOMETRIA_CONFIG", "none")

from agentfox import db  # noqa: E402
from agentfox.core.config import get_settings, reset_settings_cache  # noqa: E402
from agentfox.detection.taint import TaintTracker  # noqa: E402
from agentfox.identity.service import ensure_identity, grant_capability  # noqa: E402
from agentfox.policy import load_from_dir, save_policy  # noqa: E402
from agentfox.registry.service import register_agent, upsert_tool  # noqa: E402
from agentfox.runtime.enforcement import Enforcer  # noqa: E402

CONTAINED = {"block", "escalate"}
# Identical to benchmarks/agentdojo_e2e/run_agentdojo_e2e.py so results are comparable.
IRREVERSIBLE = re.compile(
    r"^(send_money|schedule_transaction|update_scheduled_transaction|update_password|"
    r"send_email|send_direct_message|post_webpage|delete_\w+|remove_\w+|reserve_\w+)$"
)
WRITE = re.compile(r"^(create_\w+|add_\w+|append_\w+|update_\w+|cancel_\w+|invite_\w+|share_\w+)$")


def impact_of(fn: str) -> str:
    return "irreversible" if IRREVERSIBLE.match(fn) else "write" if WRITE.match(fn) else "read"


def wipe() -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()


def setup(traces: dict, detectors: bool) -> dict[str, str]:
    wipe()
    if detectors:
        os.environ.pop("AGENTFOX_ENABLED_DETECTORS", None)
    else:
        os.environ["AGENTFOX_ENABLED_DETECTORS"] = "[]"
    reset_settings_cache()
    db.init_db()
    legit: dict[str, set[str]] = defaultdict(set)
    fns: set[str] = set()
    for b in traces["benign"]:
        for c in b["calls"]:
            legit[b["suite"]].add(c["function"])
            fns.add(c["function"])
    for a in traces["attack"]:
        for c in a["user_calls"] + a["injection_calls"]:
            fns.add(c["function"])
    slugs = {}
    with db.session_scope() as s:
        for doc in load_from_dir(get_settings().policies_dir):
            save_policy(s, doc, author="paper", notes="agentdojo inferred-provenance replay")
        for fn in sorted(fns):
            upsert_tool(
                s, f"agentdojo.{fn}", name=fn, impact=impact_of(fn), description=f"AgentDojo {fn}"
            )
        for suite in sorted(legit):
            slug = f"agentdojo-{suite}"
            agent = register_agent(
                s,
                slug,
                name=slug,
                purpose=f"AgentDojo {suite}",
                owner_email="benchmark@example.com",
                environment="production",
                risk_tier="limited",
            )
            ident = ensure_identity(s, agent)
            for fn in sorted(legit[suite]):
                tiered = os.environ.get("GRANT_MODE") == "tiered" and impact_of(fn) == "read"
                grant_capability(
                    s,
                    ident,
                    f"agentdojo.{fn}",
                    max_taint="memory" if tiered else "user",
                    requires_approval=False,
                    granted_by="paper",
                )
            slugs[suite] = slug
    return slugs


def guard(slug, call, intent, tracker, provenance):
    args = call["args"] if isinstance(call["args"], dict) else {"value": call["args"]}
    with db.session_scope() as s:
        r = Enforcer(s).guard_tool_call(
            agent_slug=slug,
            tool_key=f"agentdojo.{call['function']}",
            arguments=args,
            provenance=provenance,
            intent=intent,
            tracker=tracker,
        )
        arg_taint = dict((r.taint or {}).get("arguments") or {})
        return {
            "function": call["function"],
            "impact": impact_of(call["function"]),
            "verdict": r.effective_verdict,
            "applied": r.verdict,
            "applied_contained": r.verdict in CONTAINED,
            "contained": r.effective_verdict in CONTAINED,
            "rules": [x.get("rule_id") for x in r.rules_fired],
            "arg_taint": arg_taint,
        }


def run_trace(slug, prompt, segments, mode):
    """segments: list of (label, calls). Returns per-label lists of call results."""
    tracker = TaintTracker()
    if mode in ("inferred", "inferred_arg"):
        tracker.mark("$.prompt", "user", prompt)
    out = defaultdict(list)
    i = 0
    for label, calls in segments:
        for call in calls:
            prov = None
            if mode == "oracle":
                args = call["args"] if isinstance(call["args"], dict) else {"value": call["args"]}
                prov = {k: ("tool_result" if label == "injection" else "user") for k in args}
                t = TaintTracker()
            elif mode == "inferred_arg":
                # Argument-level only: same inference corpus, but the session's
                # message-level taint (max_source) is not carried into the decision.
                t = TaintTracker()
                t.mark("$.prompt", "user", None)
                t._content = list(tracker._content)
            else:
                t = tracker
            res = guard(slug, call, prompt, t, prov)
            out[label].append(res)
            if mode in ("inferred", "inferred_arg"):
                tracker.mark(f"$.tool[{i}]", "tool_result", call["output"])
            i += 1
    return out


def run(traces, mode, detectors):
    slugs = setup(traces, detectors)
    benign = []
    for b in traces["benign"]:
        r = run_trace(slugs[b["suite"]], b["prompt"], [("user", b["calls"])], mode)
        benign.append({"suite": b["suite"], "user_task": b["user_task"], "calls": r["user"]})
    attack = []
    for a in traces["attack"]:
        r = run_trace(
            slugs[a["suite"]],
            a["prompt"],
            [("user", a["user_calls"]), ("injection", a["injection_calls"])],
            mode,
        )
        attack.append(
            {
                "suite": a["suite"],
                "user_task": a["user_task"],
                "injection_task": a["injection_task"],
                "user_calls": r["user"],
                "injection_calls": r["injection"],
            }
        )
    return {"benign": benign, "attack": attack}


if __name__ == "__main__":
    traces = json.load(open(sys.argv[1]))
    out = {"version": traces["version"], "runs": {}}
    modes = (
        sys.argv[3].split(",")
        if len(sys.argv) > 3
        else ["oracle", "inferred", "inferred_arg", "cap_only"]
    )
    for mode in modes:
        for det in (True, False):
            t0 = time.time()
            key = f"{mode}/{'det_on' if det else 'det_off'}"
            out["runs"][key] = run(traces, mode, det)
            print(key, f"{time.time() - t0:.1f}s", flush=True)
    wipe()
    json.dump(out, open(sys.argv[2], "w"))
