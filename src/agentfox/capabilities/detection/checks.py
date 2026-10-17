"""The detection check the runtime runs on a user turn: conversation trajectory.

Registered with `platform/checks.py`; see `grounding/checks.py` for the contract.
"""

from __future__ import annotations

import logging
from typing import Any

from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.trajectory import ENTITY as TRAJECTORY_ENTITY
from agentfox.capabilities.detection.trajectory import SCAN_CHARS as TRAJECTORY_SCAN_CHARS
from agentfox.capabilities.detection.trajectory import assess as assess_trajectory
from agentfox.platform.checks import CheckContext, check

log = logging.getLogger("agentfox.runtime.enforcement")


@check(
    "detection.trajectory",
    surfaces=("input",),
    order=70,
)
def trajectory_check(ctx: CheckContext) -> dict[str, Any]:
    """Whether the *conversation* is escalating, not whether this turn is.

    Built to the shape `grounding/checks.py:commitment_check` established, for the same reason: the
    finding is recorded and surfaced on the `action["risks"]` channel, and nothing
    here decides a verdict. See `trajectory.py` for the measurement.

    Why this is the integration point. The trajectory score hangs off the per-turn
    recording hook, because a check with a natural per-turn hook to attach to gets
    called on live traffic. `check_conversation_window` is that hook on this path:
    it already runs once per user turn, already holds a `session_id` and the
    recorded history behind it, and is already called from `autoguard._govern`'s
    pre-flight and the gateway playground route. Nothing else needed wiring, which
    is the whole point — `docs/design/failure-modes.md` exists to catch modules that
    are built and never called, and a trajectory scorer reachable only from its own
    tests would be exactly that.

    **Sub-threshold detector activations.** The trajectory score's first component
    is a detector finding above zero and below the blocking threshold. The
    per-message run for the *current* turn already exists, but the equivalent number
    for the earlier turns in the window is not persisted anywhere —
    `ConversationTurn.signals_json` is written by `escalation.record_turn` and
    carries escalation's signals, not detector scores. So each turn in the window is
    scored here, through the real pipeline, at a measured ~0.4ms per turn. Worth
    knowing what that buys: `benchmarks/crescendo/` measures the shipped detectors
    returning **exactly zero on all 132 turns** of that corpus, so on crescendo
    traffic this component contributes nothing and the drift and reframing
    components are doing all the work. It is kept because it is cheap and because a
    conversation that mixes gradual escalation with clumsier probing is the case
    where it pays.
    """
    surface, window = ctx.surface, ctx.conversation_window
    if surface != "input" or not window or len(window) < 3:
        return {}

    # Never let a governance extra break a request, and never let it eat the
    # budget: the per-turn scoring is bounded by the window size (<= 8 short
    # strings) and skipped wholesale if anything goes wrong.
    try:
        detector_scores = window_detector_scores(ctx.pipeline, window)
        assessment = assess_trajectory(window, detector_scores=detector_scores)
    except Exception as exc:  # pragma: no cover - defence in depth
        log.debug("agentfox: trajectory scoring skipped: %s", exc)
        return {}

    out: dict[str, Any] = {"trajectory": assessment.to_json()}
    if not assessment.fired:
        return out
    out["evidence_issues"] = [
        {
            "type": "trajectory_drift",
            # High, never critical: a `critical` entry in `action["risks"]` is
            # hard-blocked by the action-assurance branch in `evaluate()`, and
            # trajectory is observe-first. Same cap, same reason, as the commitment
            # findings.
            "severity": "high",
            "title": f"{TRAJECTORY_ENTITY}: {assessment.reason}",
            "entity": TRAJECTORY_ENTITY,
            "control_keys": ["NOM-RTG-06"],
        }
    ]
    out["risks"] = [
        {
            "code": assessment.code,
            "severity": "high",
            "detail": assessment.reason,
            "evidence": assessment.to_json(),
        }
    ]
    return out


def window_detector_scores(pipeline: Any, window: list[str]) -> list[float]:
    """Each window turn's per-message detector max score (the trajectory's first component).

    Runs the same pipeline the per-message path runs, one short turn at a time.
    A degraded or erroring run contributes 0.0 rather than failing the check —
    the component is additive, so a missing one under-reports rather than
    inventing a trajectory.

    Capped at `trajectory.SCAN_CHARS` per turn, and that cap is load-bearing
    rather than tidy: this runs the pipeline once *per turn in the window*,
    so an uncapped 250KB turn costs about 2.5 seconds against a 300ms budget.
    The per-message path still sees the whole message; what is bounded here is
    only the proxy feeding the trajectory score.
    """
    context = DetectionContext(surface="input", taint_source="user")
    scores: list[float] = []
    for text in window:
        try:
            scores.append(pipeline.run(text[:TRAJECTORY_SCAN_CHARS], context).max_score)
        except Exception:  # pragma: no cover - defence in depth
            scores.append(0.0)
    return scores
