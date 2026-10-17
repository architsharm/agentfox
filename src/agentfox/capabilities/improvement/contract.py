"""The vocabulary and the non-negotiable rules the improvement loop shares.

Every workstream — proposals, findings hygiene, the scheduler, the canary gate, the
loops that generate proposals — imports its terms from here, so "loosens", "L3" and
"verified" mean one thing everywhere. The rules in this module are deliberately small,
pure and exhaustively tested: they are the part of the system whose failure would turn a
governance product into one that quietly rewrites its own guardrails.
"""

from __future__ import annotations

# --- lifecycle ---------------------------------------------------------------
PROPOSED = "proposed"
PROVEN = "proven"
APPROVED = "approved"
CANARY = "canary"
APPLIED = "applied"
VERIFIED = "verified"
REJECTED = "rejected"
ROLLED_BACK = "rolled_back"
SUPERSEDED = "superseded"

STATUSES = (
    PROPOSED,
    PROVEN,
    APPROVED,
    CANARY,
    APPLIED,
    VERIFIED,
    REJECTED,
    ROLLED_BACK,
    SUPERSEDED,
)
TERMINAL = frozenset({VERIFIED, REJECTED, ROLLED_BACK, SUPERSEDED})
#: Still awaiting a decision or an outcome — the set dedupe and inbox views care about.
OPEN = frozenset({PROPOSED, PROVEN, APPROVED, CANARY, APPLIED})

#: The only legal moves. Anything else is a bug, and ``transition_allowed`` says so.
TRANSITIONS: dict[str, frozenset[str]] = {
    PROPOSED: frozenset({PROVEN, REJECTED, SUPERSEDED}),
    PROVEN: frozenset({APPROVED, REJECTED, SUPERSEDED}),
    APPROVED: frozenset({CANARY, APPLIED, REJECTED, SUPERSEDED}),
    CANARY: frozenset({APPLIED, ROLLED_BACK}),
    APPLIED: frozenset({VERIFIED, ROLLED_BACK}),
    VERIFIED: frozenset(),
    REJECTED: frozenset(),
    ROLLED_BACK: frozenset(),
    SUPERSEDED: frozenset(),
}

# --- direction and autonomy ---------------------------------------------------
TIGHTENS = "tightens"
LOOSENS = "loosens"
NEUTRAL = "neutral"
DIRECTIONS = (TIGHTENS, LOOSENS, NEUTRAL)

AUTONOMY_LEVELS = ("L0", "L1", "L2", "L3", "L4")
#: L0 observe · L1 recommend · L2 one-click (human approves) · L3 auto-apply ·
#: L4 autonomous hygiene. Only L3 and L4 ever apply without a person deciding, and only
#: a change that does not loosen (`may_apply_automatically`). Nothing here puts an
#: automated change in observe mode first: a kind that should be staged says so in its
#: diff (``stage: canary``), and its applier stages it.
AUTO_APPLY_LEVELS = frozenset({"L3", "L4"})

SCOPE_LEVELS = ("org", "team", "agent", "user")

#: Kinds of change no track record can make automatic. The list mirrors the design's
#: "Never automatic" row and is checked in addition to direction, so a kind cannot slip
#: through by being mislabelled neutral.
NEVER_AUTOMATIC_KINDS = frozenset(
    {
        "control.loosen",
        "control.disable",
        "grant.widen",
        "verdict.unblock",
        "agent.kill",
        "agent.resume",
        "compliance.claim",
        "learning.cross_tenant",
        "audit.chain",
    }
)


def transition_allowed(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def may_apply_automatically(*, direction: str, kind: str, autonomy_level: str) -> bool:
    """Can the loop apply this change with no person deciding?

    Three conditions, all required: the class has earned an auto-apply level, the kind
    is not on the never-automatic list, and the change does not loosen anything. The
    last one is not a threshold that can be tuned — it is the rule.
    """
    if direction not in DIRECTIONS:
        return False
    if direction == LOOSENS:
        return False
    if kind in NEVER_AUTOMATIC_KINDS:
        return False
    return autonomy_level in AUTO_APPLY_LEVELS


def may_rollback_automatically(*, direction: str) -> bool:
    """Can the loop undo this change with no person deciding?

    Undoing a change runs its direction backwards. Reverting a tightening loosens a
    control, so it falls under the same rule as any other loosening: a person decides.
    Reverting a loosening or a neutral change is always safe to automate.
    """
    return direction in DIRECTIONS and direction != TIGHTENS


def requires_second_approver(*, direction: str, scope_level: str) -> bool:
    """A loosening at org level needs two named people."""
    return direction == LOOSENS and scope_level == "org"


def lower_autonomy(level: str) -> str:
    """One level down, never below L1: a demoted class keeps recommending."""
    if level not in AUTONOMY_LEVELS:
        return "L1"
    index = AUTONOMY_LEVELS.index(level)
    return AUTONOMY_LEVELS[max(1, index - 1)]


__all__ = [name for name in dir() if not name.startswith("_")]
