"""The shared vocabulary: names and orderings that several layers reason over.

Surfaces, the provenance order, effect precedence, argument comparators and the
automation actor type are used by detection, policy, identity, containment, the
improvement loop and the audit chain alike. They live here, in the kernel, so that
none of those packages has to import another just to read a constant.
"""

from __future__ import annotations

import re
from typing import Any

# Surfaces a detector can run on. The agent-native point is that `input` is the
# *least* interesting one: indirect injection arrives via retrieved content and
# tool results.
#
# `memory_write` and `agent_message` are deliberately distinct from
# `tool_args`/`tool_result`: a write into an agent's long-term store and a sub-agent's
# claim are not the same trust boundary as a tool call or its return value.
SURFACES = (
    "input",
    "output",
    "tool_args",
    "tool_result",
    "retrieved",
    "memory_write",
    "agent_message",
    # The agent declaring itself finished. Not content arriving or leaving —
    # a claim, checked against what actually happened. See
    # `Enforcer.guard_completion`.
    "completion",
    # The model's own reasoning, before it acts on it. The only surface where a
    # detection means the payload was *adopted* rather than merely present —
    # see `Enforcer.guard_reasoning`.
    "reasoning",
)

# Trust sources, ordered least → most dangerous. Used for taint comparison.
TAINT_ORDER = ("none", "user", "retrieved", "tool_result", "subagent", "memory")


def taint_rank(source: str) -> int:
    try:
        return TAINT_ORDER.index(source)
    except ValueError:
        return len(TAINT_ORDER)


#: Effect precedence — a decision takes the strongest effect any rule produced.
EFFECT_RANK: dict[str, int] = {
    "allow": 0,
    "tokenize": 1,
    "mask": 2,
    "redact": 3,
    # `abstain` withholds the answer without treating the user as an adversary,
    # which is strictly stronger than redacting part of one and strictly weaker than
    # pulling a human in.
    "abstain": 4,
    "escalate": 5,
    "block": 6,
}

#: Argument comparison operators, shared by policy conditions, capability limits and
#: business ladders.
COMPARATORS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: _num(a) > _num(b),
    "gte": lambda a, b: _num(a) >= _num(b),
    "lt": lambda a, b: _num(a) < _num(b),
    "lte": lambda a, b: _num(a) <= _num(b),
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
    "matches": lambda a, b: bool(re.search(str(b), str(a))),
}


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


#: Audit actor type for every change the platform makes on its own. Distinct from
#: "user", "operator" and "agent" so an automated change is never recorded as a human
#: decision.
AUTOMATION_ACTOR_TYPE = "automation"

__all__ = [
    "AUTOMATION_ACTOR_TYPE",
    "COMPARATORS",
    "EFFECT_RANK",
    "SURFACES",
    "TAINT_ORDER",
    "taint_rank",
]
