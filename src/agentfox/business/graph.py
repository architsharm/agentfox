"""One decision graph from many authors, and the conflicts between them.

Governance does not arrive from one place. Finance writes the refund thresholds, Legal
writes the disclosure rules, Security writes the injection policy, and a platform team
writes whatever the first three forgot. Each is correct in isolation. The failure is in
the seam: two teams set different thresholds on the same field and nobody notices until
a refund that Finance meant to review is auto-approved because Support's rule ran
first.

Three things this module does, in order of how much they matter:

**Detect contradiction.** Two ladders on the same field with different outcomes at the
same value is not a merge to be resolved by precedence — it is a disagreement between
two humans, and resolving it silently means one of them is wrong and does not know.
Precedence is applied *and reported*, with both authors named.

**Show the resolved graph.** A policy you cannot read is a policy nobody audits. The
compiled graph is the actual decision path — which guardrail runs at which stage, in
what order, and what each can produce — rather than the union of what people wrote.

**Compose the two algebras correctly.** Security rules take the lattice maximum;
business ladders select exactly one band. Where both apply, **security dominates**: a
band that says auto-approve can never override a rule that says block. The reverse
would let a business exception quietly disable a security control, which is precisely
the failure the hierarchical `restrict`/`override` semantics exist to prevent one level
up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentfox.policy.model import EFFECT_RANK
from agentfox.business.ladder import Ladder, LadderDecision
from agentfox.business.ladder import evaluate as evaluate_ladder

#: Business outcomes mapped onto the security lattice, so the two can be compared.
#: `verify` sits just above allow: it permits the action conditionally, which is
#: stronger than allowing outright and weaker than pulling in a human.
BUSINESS_RANK = {
    "allow": EFFECT_RANK["allow"],
    "verify": EFFECT_RANK["tokenize"],
    "redact": EFFECT_RANK["redact"],
    "escalate": EFFECT_RANK["escalate"],
    "block": EFFECT_RANK["block"],
}


@dataclass
class Conflict:
    """Two authors disagreeing about the same thing."""

    code: str
    severity: str
    detail: str
    left: str = ""
    right: str = ""
    field_path: str = ""
    at_value: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "between": [self.left, self.right],
            "field": self.field_path,
            "at_value": self.at_value,
        }


def _sample_points(ladders: list[Ladder]) -> list[float]:
    """Values worth testing: every boundary, either side of it, and zero.

    Comparing two ladders analytically means intersecting interval sets; sampling the
    boundaries finds the same disagreements with far less machinery, because a
    disagreement between two step functions always shows up at a step.
    """
    points: set[float] = {0.0}
    for ladder in ladders:
        for band in ladder.bands:
            if band.upto is None:
                continue
            points.update({band.upto, band.upto + 0.01, max(0.0, band.upto - 0.01)})
    highest = max((b.upto or 0) for lad in ladders for b in lad.bands) if ladders else 0
    points.add(highest * 10 + 1000)
    return sorted(points)


def find_conflicts(ladders: list[Ladder]) -> list[Conflict]:
    """Where two authors' ladders disagree, and where one has a problem on its own."""
    conflicts: list[Conflict] = []

    by_scope: dict[tuple[str | None, str], list[Ladder]] = {}
    for ladder in ladders:
        by_scope.setdefault((ladder.tool, ladder.field_path), []).append(ladder)

    for (_tool, field_path), group in by_scope.items():
        # A single ladder can still be wrong on its own terms.
        for ladder in group:
            units = {ladder.unit}
            if len(units) > 1:  # pragma: no cover - defensive
                continue
            for index, band in enumerate(ladder.bands):
                if band.outcome == "verify" and band.verify is None:  # pragma: no cover
                    conflicts.append(
                        Conflict(
                            "verify-unconfigured",
                            "high",
                            f"band {index} verifies nothing",
                            ladder.key,
                            "",
                            field_path,
                        )
                    )

        if len(group) < 2:
            continue

        # Different units on the same field is a category error, not a precedence
        # question: one team's 100 is another team's 1.00.
        units = {ladder.unit for ladder in group}
        if len(units) > 1:
            conflicts.append(
                Conflict(
                    "unit-mismatch",
                    "critical",
                    f"ladders on '{field_path}' declare different units {sorted(units)} — "
                    "one team's 100 is another's 1.00, and no precedence rule makes that safe",
                    group[0].key,
                    group[1].key,
                    field_path,
                )
            )
            continue

        for value in _sample_points(group):
            outcomes: dict[str, list[str]] = {}
            for ladder in group:
                decision = evaluate_ladder(ladder, _synthetic(ladder, value))
                outcomes.setdefault(decision.outcome, []).append(ladder.key)
            if len(outcomes) > 1:
                ordered = sorted(outcomes, key=lambda o: -BUSINESS_RANK.get(o, 0))
                strongest, weakest = ordered[0], ordered[-1]
                conflicts.append(
                    Conflict(
                        "contradiction",
                        "high",
                        f"at {field_path} = {value:g} ({group[0].unit}), "
                        f"'{outcomes[strongest][0]}' says {strongest} and "
                        f"'{outcomes[weakest][0]}' says {weakest}. The stricter wins, but "
                        "one of the two authors believes something that is not happening",
                        outcomes[strongest][0],
                        outcomes[weakest][0],
                        field_path,
                        value,
                    )
                )
                break  # one report per pair is enough; the rest are the same argument

    return conflicts


def _synthetic(ladder: Ladder, value: float) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    cursor = payload
    parts = ladder.field_path.split(".")
    for part in parts[:-1]:
        cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value
    return payload


# ---------------------------------------------------------------------------
# Combined decision
# ---------------------------------------------------------------------------


@dataclass
class CombinedDecision:
    """The outcome of security policy and business ladders together."""

    verdict: str = "allow"
    security_verdict: str = "allow"
    business_outcome: str = "allow"
    ladder: LadderDecision | None = None
    #: True when a business rule wanted something weaker than security allowed.
    security_dominated: bool = False
    reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "security_verdict": self.security_verdict,
            "business_outcome": self.business_outcome,
            "security_dominated": self.security_dominated,
            "reason": self.reason,
            "ladder": self.ladder.to_json() if self.ladder else None,
        }


def combine(security_verdict: str, ladder_decision: LadderDecision | None) -> CombinedDecision:
    """Security dominates. A business band may tighten, never loosen.

    An auto-approve band must not be able to override a block — otherwise a refund
    threshold written by Finance becomes a way to disable an injection control written
    by Security, and neither author would ever see it.
    """
    combined = CombinedDecision(
        security_verdict=security_verdict, verdict=security_verdict, ladder=ladder_decision
    )
    if ladder_decision is None or not ladder_decision.matched:
        if ladder_decision is not None and ladder_decision.undecidable:
            # An undecidable ladder is not an absent one.
            combined.business_outcome = ladder_decision.outcome
            combined.verdict = _stronger(security_verdict, ladder_decision.outcome)
            combined.reason = ladder_decision.undecidable
        return combined

    combined.business_outcome = ladder_decision.outcome
    strongest = _stronger(security_verdict, ladder_decision.outcome)
    combined.verdict = strongest
    if BUSINESS_RANK.get(ladder_decision.outcome, 0) < EFFECT_RANK.get(security_verdict, 0):
        combined.security_dominated = True
        combined.reason = (
            f"business rule wanted '{ladder_decision.outcome}' but security says "
            f"'{security_verdict}' — a band cannot loosen a security verdict"
        )
    else:
        combined.reason = ladder_decision.reason
    return combined


def _stronger(security: str, business: str) -> str:
    if BUSINESS_RANK.get(business, 0) > EFFECT_RANK.get(security, 0):
        return business
    return security


# ---------------------------------------------------------------------------
# The readable graph
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    stage: str
    kind: str
    key: str
    owner: str = ""
    effects: list[str] = field(default_factory=list)
    detail: str = ""
    inert_because: str = ""


STAGE_ORDER = ["input", "retrieval", "tool_args", "output", "conversation", "offline"]


def build_graph(
    ladders: list[Ladder] | None = None,
    policy_keys: list[str] | None = None,
    supplied_inputs: set[str] | None = None,
) -> list[GraphNode]:
    """The decision path as it will actually run, stage by stage.

    ``supplied_inputs`` is what the caller's requests actually carry. Anything a
    guardrail needs and does not get is reported as inert rather than shown as active
    — a control listed as configured but never reachable is worse than one that is
    visibly missing, because it reads as coverage.
    """
    from agentfox.business.catalogue import CATALOGUE

    supplied = supplied_inputs or set()
    nodes: list[GraphNode] = []

    for kind in CATALOGUE:
        missing = [need for need in kind.inputs if need not in supplied] if supplied else []
        nodes.append(
            GraphNode(
                stage=kind.stage,
                kind=kind.id,
                key=kind.id,
                effects=list(kind.effects),
                detail=kind.decides,
                inert_because="; ".join(missing) if missing else "",
            )
        )

    for ladder in ladders or []:
        nodes.append(
            GraphNode(
                stage="tool_args",
                kind="threshold_ladder",
                key=ladder.key,
                owner=ladder.owner,
                effects=sorted({band.outcome for band in ladder.bands}),
                detail=f"{ladder.field_path} in {ladder.unit}, {len(ladder.bands)} bands",
            )
        )

    for key in policy_keys or []:
        nodes.append(
            GraphNode(
                stage="output",
                kind="policy_document",
                key=key,
                effects=["allow", "redact", "escalate", "block"],
            )
        )

    nodes.sort(key=lambda n: (STAGE_ORDER.index(n.stage) if n.stage in STAGE_ORDER else 99, n.key))
    return nodes
