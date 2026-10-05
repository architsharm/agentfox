"""Learned permissions: observe what an agent calls, propose the grants, a person approves.

Default deny is enforced from the first call, and the minimum manual path to a working
support bot was four `tools declare`, four `capability grant` and a page of reading
about provenance levels. Every fact those commands need was already recorded: each
tool call — allowed or refused — leaves a :class:`~agentfox.models.Decision` with the
tool, its arguments, their provenance and every rule that fired, and an ``agent
calls_tool`` lineage edge. This loop reads them and files two kinds of proposal:

* ``tool.declare`` for a tool the registry has never heard of, with an impact guessed
  from its name (``integrations.mcp.infer_impact``, plus money-movement and messaging
  words that guess misses). A guess, said to be one; a person confirms it.
* ``capability.grant`` per agent × tool, with argument limits read off the observed
  values (the largest amount, the recipient domains, a short list of codes) and a
  provenance ceiling matching what was observed — both **from benign calls only**.
  An injected call is held, and an attacker's recipient domain or amount read into
  a limit is a limit a reviewer approves without noticing.

What counts as benign is the whole safety argument, so it is narrow:

* A call refused *only* because no grant existed, the tool was undeclared or no intent
  was declared is benign: those say nothing about the call, only about configuration.
* A call stopped for its provenance (``taint.*``, ``composition.escalation``, a
  grant's own ceiling) is held back — unless a person approved it in the approval
  queue. An injected call looks exactly like this, so the loop never learns a wider
  ceiling from traffic nobody looked at.
* A call a detector matched, that broke a limit, or that any other rule stopped, is
  flagged and never learned from. Nor is a call whose approval was denied.

Every proposal is a loosening, so it is filed for a person: approval through the
ordinary lifecycle, never automation. A proposal carries a replay proof — every
benign call it was learned from passes the proposed grant — which is what moves it
to ``proven``. A later run marks an applied grant ``verified`` once the agent has used
it without a capability refusal.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import chain
from ..guardrails.base import taint_rank
from ..identity.service import _constraint_ok
from ..models import (
    Agent,
    ApprovalRequest,
    Capability,
    ChangeProposal,
    Decision,
    Identity,
    LineageEdge,
    Tool,
    as_aware,
    utcnow,
)
from . import contract
from .loops import SUPERSEDE_ACTION, LoopReport
from .proposals import SUBJECT_TYPE, attach_proof, file_proposal, verify_proposal

SOURCE = "traffic.observed"
GRANT_KIND = "capability.grant"
DECLARE_KIND = "tool.declare"

#: Rules that say something about the deployment's configuration, not about the call.
#: A call refused only by these is evidence of what the agent legitimately does.
CONFIGURATION_RULES = frozenset(
    {
        "capability.denied",
        "capability.default_deny",
        "tool.not_declared",
        "intent.undeclared_irreversible",
    }
)
#: Rules about where the call's arguments came from. An injected call trips exactly
#: these, so such a call is only learned from once a person approved it.
PROVENANCE_RULES = frozenset(
    {
        "taint.irreversible_tool",
        "taint.high_impact_tool",
        "taint.write_from_tool_result",
        "composition.escalation",
        "capability.requires_approval",
        "capability.approval_required",
    }
)

#: Words `infer_impact` does not treat as irreversible but a person would: money moves
#: and messages leave. Kept here rather than added to `infer_impact`, which also decides
#: impact for every MCP tool registered at runtime — this only shapes a suggestion a
#: person reviews.
_IRREVERSIBLE_WORDS = (
    "refund",
    "pay",
    "charge",
    "transfer",
    "wire",
    "email",
    "sms",
    "message",
    "notify",
    "publish",
    "cancel",
    "close",
)

_TAINT_PHRASE = {
    "retrieved": "retrieved documents",
    "tool_result": "other tools' output",
    "subagent": "a sub-agent's output",
    "memory": "long-term memory",
}
_IMPACT_PHRASE = {
    "read": "read-only",
    "write": "a write",
    "high_impact": "high-impact",
    "irreversible": "irreversible",
}
_EMAIL = re.compile(r"^[^@\s]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})$")
_URL = re.compile(r"^(https?)://([A-Za-z0-9.-]+)(?::\d+)?(?:[/?#]\S*)?$")
#: A string argument with no more distinct values than this, seen at least
#: `_ENUM_MIN_CALLS` times and never longer than `_ENUM_MAX_LEN`, is proposed as a list.
_ENUM_MAX_DISTINCT = 3
_ENUM_MIN_CALLS = 3
_ENUM_MAX_LEN = 32


@dataclass
class TrafficReport(LoopReport):
    #: Applied grants the loop marked verified: used since, no capability refusal.
    verified: list[str] = field(default_factory=list)
    #: Calls examined, by how they were classified.
    calls: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {**super().to_json(), "verified": self.verified, "calls": self.calls}


# ---------------------------------------------------------------------------
# Reading the traffic
# ---------------------------------------------------------------------------


@dataclass
class ObservedCall:
    decision_id: str
    agent: str
    tool_key: str
    arguments: dict[str, Any]
    #: The provenance policy reasoned over for this call: the session's worst under
    #: `taint_scope = session`, the arguments' worst under `argument`.
    provenance: str
    tool_known: bool
    #: benign | held | flagged
    verdict: str
    why: str
    #: Stopped for its provenance, then approved by a person in the approval queue.
    approved: bool = False
    at: dt.datetime | None = None


def _worst(sources: list[str]) -> str:
    worst = "none"
    for source in sources:
        if taint_rank(source) > taint_rank(worst):
            worst = source
    return worst


def _is_personal_data(entity: str) -> bool:
    return entity.upper().startswith("PII")


def _personal_data_rule(rule: dict[str, Any]) -> bool:
    """A rule whose only trigger is personal data in the arguments.

    Personal data is what a support bot's tools legitimately move — an email address
    is the point of `send_email` — and whether it may leave is a data-protection rule
    that a grant does not touch: it keeps firing after the grant exactly as before. So
    it is not evidence of an attack and does not stop a call being learned from. An
    injection or a credential is, and does.
    """
    entities = [str(e) for e in rule.get("entities") or []]
    prefixes = [str(p) for p in rule.get("entity_prefixes") or []]
    named = entities + prefixes
    return bool(named) and all(_is_personal_data(n) for n in named)


def classify(
    decision: Decision, approval: ApprovalRequest | None, impact: str | None = None
) -> tuple[str, str]:
    """``(benign | held | flagged, why)`` for one recorded tool call.

    ``impact`` is the tool's impact as known now — declared, or guessed from its name
    if it is still undeclared. A call to a tool recorded as ``read`` (which is what an
    undeclared tool is reasoned about as) that is really something more never had its
    provenance checked by the rules that would have applied, so untrusted provenance
    on it is held exactly as if those rules had fired.
    """
    taint = decision.taint_summary_json or {}
    if approval is not None and approval.status in ("denied", "expired"):
        return "flagged", f"a person {approval.status} its approval"
    attack = sorted(
        {
            str(d.get("entity_type"))
            for d in taint.get("detections") or []
            if not _is_personal_data(str(d.get("entity_type")))
        }
    )
    if attack:
        return "flagged", f"a detector matched ({', '.join(attack[:3])})"
    rules = list(decision.rules_fired_json or [])
    fired = {str(r.get("rule_id")) for r in rules}
    other = sorted(
        str(r.get("rule_id"))
        for r in rules
        if str(r.get("rule_id")) not in CONFIGURATION_RULES
        and str(r.get("rule_id")) not in PROVENANCE_RULES
        and not _personal_data_rule(r)
    )
    if other:
        return "flagged", f"{other[0]} fired"
    provenance = sorted(fired & PROVENANCE_RULES)
    approved = approval is not None and approval.status == "approved"
    if provenance:
        if approved:
            return "benign", f"{' and '.join(provenance)} fired and a person approved the call"
        return "held", " and ".join(provenance)
    unassessed = (
        impact not in (None, "read")
        and str(taint.get("tool_impact") or "read") == "read"
        and taint_rank(_observed_provenance(taint)) > taint_rank("user")
    )
    if unassessed and not approved:
        return "held", "untrusted provenance on a tool whose impact was unknown when called"
    return "benign", "refused only for configuration" if fired else "allowed"


def _observed_provenance(taint: dict[str, Any]) -> str:
    arguments = [str(v) for v in (taint.get("arguments") or {}).values()]
    if taint.get("scope") == "argument":
        return _worst(arguments)
    return _worst([str(taint.get("max_source") or "none"), *arguments])


def observed_calls(
    session: Session, *, agent: str | None = None, since: dt.datetime | None = None
) -> list[ObservedCall]:
    """Every recorded tool call in the window, classified. Oldest first."""
    agents = {a.id: a.slug for a in session.scalars(select(Agent))}
    declared = {t.key: t.impact for t in session.scalars(select(Tool))}
    query = select(Decision).where(Decision.surface == "tool_args", Decision.tool_key.is_not(None))
    if since is not None:
        query = query.where(Decision.created_at >= since)
    if agent is not None:
        ids = [i for i, slug in agents.items() if slug == agent]
        query = query.where(Decision.agent_id.in_(ids))
    out: list[ObservedCall] = []
    for decision in session.scalars(query.order_by(Decision.created_at)):
        slug = agents.get(decision.agent_id or "")
        if slug is None:
            continue
        approval = (
            session.get(ApprovalRequest, decision.approval_id) if decision.approval_id else None
        )
        tool_key = str(decision.tool_key)
        impact = declared.get(tool_key) or infer_declared_impact(tool_key)
        verdict, why = classify(decision, approval, impact)
        taint = decision.taint_summary_json or {}
        fired = {str(r.get("rule_id")) for r in decision.rules_fired_json or []}
        out.append(
            ObservedCall(
                decision_id=decision.id,
                agent=slug,
                tool_key=str(decision.tool_key),
                arguments=dict(taint.get("arguments_snapshot") or {}),
                provenance=_observed_provenance(taint),
                tool_known="tool.not_declared" not in fired,
                verdict=verdict,
                why=why,
                approved=bool(approval is not None and approval.status == "approved"),
                at=as_aware(decision.created_at),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Suggesting limits
# ---------------------------------------------------------------------------


def _leaves(arguments: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Dotted path -> value, for the shapes a grant constraint can address."""
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_leaves(value, f"{path}."))
        elif not isinstance(value, list):
            out[path] = value
    return out


def nice_ceiling(value: float) -> float | int:
    """Round up to two significant figures: 112 -> 120, 45.5 -> 46, 7 -> 7.

    A limit at exactly the largest amount ever seen refuses the next ordinary refund
    that is a cent bigger; a limit at ten times it is not a limit. Two significant
    figures, rounded up, is headroom a person can read at a glance.
    """
    if value <= 0:
        return 0
    magnitude = 10 ** (math.floor(math.log10(value)) - 1)
    ceiling = math.ceil(value / magnitude - 1e-9) * magnitude
    ceiling = round(ceiling, max(0, -math.floor(math.log10(magnitude))))
    return int(ceiling) if float(ceiling).is_integer() else ceiling


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


@dataclass
class Limit:
    path: str
    spec: Any
    phrase: str
    #: What was seen, for the title's parenthesis.
    seen: str = ""


def suggest_limits(calls: list[dict[str, Any]]) -> list[Limit]:
    """Argument limits read off the observed values. Only arguments present in every
    call are constrained: a limit on an argument a call omits refuses that call."""
    if not calls:
        return []
    flattened = [_leaves(c) for c in calls]
    common = set(flattened[0])
    for leaves in flattened[1:]:
        common &= set(leaves)
    limits: list[Limit] = []
    for path in sorted(common):
        values = [leaves[path] for leaves in flattened]
        if all(_is_number(v) for v in values):
            largest = max(values)
            if largest <= 0:
                continue
            ceiling = nice_ceiling(float(largest))
            shown = int(largest) if float(largest).is_integer() else largest
            limits.append(Limit(path, {"lte": ceiling}, f"{path} ≤ {ceiling}", f"max {shown}"))
            continue
        if not all(isinstance(v, str) for v in values):
            continue
        hosts = [_URL.match(v.strip()) for v in values]
        if all(hosts):
            names = sorted({m.group(2).lower() for m in hosts if m})
            pattern = "^https?://(" + "|".join(re.escape(h) for h in names) + ")(?::\\d+)?(/|$)"
            limits.append(Limit(path, {"matches": pattern}, f"{path} on {' or '.join(names)}"))
            continue
        domains = [_EMAIL.match(v.strip()) for v in values]
        if all(domains):
            names = sorted({m.group(1).lower() for m in domains if m})
            pattern = "^[^@\\s]+@(" + "|".join(re.escape(d) for d in names) + ")$"
            limits.append(Limit(path, {"matches": pattern}, f"{path} at {' or '.join(names)}"))
            continue
        distinct = sorted(set(values))
        if (
            # One value seen every time is as likely a repeated identifier as a code;
            # a list of one would refuse the next customer. Two or more is a pattern.
            2 <= len(distinct) <= _ENUM_MAX_DISTINCT
            and len(values) >= _ENUM_MIN_CALLS
            and len(distinct) < len(values)
            and max(len(v) for v in distinct) <= _ENUM_MAX_LEN
            # Codes (USD, priority-high), not prose: a short list of sentences is a
            # coincidence of a small sample, not a limit anyone meant.
            and not any(ch.isspace() for v in distinct for ch in v)
        ):
            limits.append(Limit(path, {"in": distinct}, f"{path} one of {', '.join(distinct)}"))
    return limits


def infer_declared_impact(tool_key: str) -> str:
    from ..integrations.mcp import infer_impact

    name = tool_key.rsplit("/", 1)[-1]
    impact = infer_impact(name)
    if impact != "irreversible" and any(w in name.lower() for w in _IRREVERSIBLE_WORDS):
        return "irreversible"
    return impact


# ---------------------------------------------------------------------------
# Filing
# ---------------------------------------------------------------------------


def _fingerprint(kind: str, agent: str, tool_key: str, diff: dict[str, Any]) -> str:
    raw = f"{kind}|{agent}|{tool_key}|{json.dumps(diff, sort_keys=True, default=str)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _supersede(session: Session, *, kind: str, agent: str, tool_key: str, keep: str) -> list[str]:
    """An undecided proposal for the same agent and tool, computed from older traffic,
    is replaced rather than left to be approved against numbers that no longer hold."""
    out: list[str] = []
    for stale in session.scalars(
        select(ChangeProposal).where(
            ChangeProposal.kind == kind,
            ChangeProposal.source == SOURCE,
            ChangeProposal.status.in_([contract.PROPOSED, contract.PROVEN]),
            ChangeProposal.id != keep,
        )
    ):
        diff = stale.diff_json or {}
        if (diff.get("agent", "*"), diff.get("tool_key")) != (agent, tool_key):
            continue
        from_status = stale.status
        stale.status = contract.SUPERSEDED
        stale.outcome_note = f"superseded by {keep}: newer traffic suggests a different change"
        stale.decided_at = utcnow()
        session.flush()
        chain.append(
            session,
            SUPERSEDE_ACTION,
            **chain.attribution(automated=True),
            subject_type=SUBJECT_TYPE,
            subject_id=stale.id,
            payload={"from_status": from_status, "superseded_by": keep},
        )
        out.append(stale.id)
    return out


def _file(
    session: Session,
    report: TrafficReport,
    *,
    kind: str,
    agent: str,
    tool_key: str,
    scope_level: str,
    scope_id: str,
    target_type: str,
    title: str,
    rationale: str,
    diff: dict[str, Any],
    evidence: dict[str, Any],
    expected_effect: dict[str, Any],
    proof: dict[str, Any],
    proof_passed: bool,
) -> ChangeProposal:
    fingerprint = _fingerprint(kind, agent, tool_key, diff)
    existing = set(
        session.scalars(select(ChangeProposal.id).where(ChangeProposal.fingerprint == fingerprint))
    )
    proposal = file_proposal(
        session,
        kind=kind,
        source=SOURCE,
        target_type=target_type,
        target_ref=tool_key if kind == DECLARE_KIND else f"{agent}:{tool_key}",
        scope_level=scope_level,
        scope_id=scope_id,
        title=title,
        rationale=rationale,
        direction=contract.LOOSENS,
        diff=diff,
        evidence=evidence,
        expected_effect=expected_effect,
        autonomy_level="L1",
        fingerprint=fingerprint,
    )
    (report.refreshed if proposal.id in existing else report.filed).append(proposal.id)
    if proposal.status == contract.PROPOSED:
        attach_proof(session, proposal, proof, passed=proof_passed)
    report.superseded += _supersede(
        session,
        kind=kind,
        agent=agent if kind == GRANT_KIND else "*",
        tool_key=tool_key,
        keep=proposal.id,
    )
    return proposal


def _live_grants(session: Session, agent: str) -> list[Capability]:
    record = session.scalar(select(Agent).where(Agent.slug == agent))
    if record is None:
        return []
    identity = session.scalar(select(Identity).where(Identity.agent_id == record.id))
    if identity is None:
        return []
    now = utcnow()
    return [
        c
        for c in session.scalars(select(Capability).where(Capability.identity_id == identity.id))
        if (as_aware(c.expires_at) or now + dt.timedelta(seconds=1)) > now
    ]


def _matching_grant(grants: list[Capability], tool_key: str) -> Capability | None:
    import fnmatch

    matches = [c for c in grants if fnmatch.fnmatch(tool_key, c.tool_key)]
    if not matches:
        return None
    return sorted(matches, key=lambda c: ("*" in c.tool_key, -len(c.tool_key)))[0]


def _within_limits(constraints: dict[str, Any], call: ObservedCall) -> bool:
    from ..identity.service import RESERVED_CONSTRAINTS

    for path, spec in (constraints or {}).items():
        if path in RESERVED_CONSTRAINTS:
            continue
        value: Any = call.arguments
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        ok, _why = _constraint_ok(value, spec)
        if not ok:
            return False
    return True


def _passes(constraints: dict[str, Any], max_taint: str, call: ObservedCall) -> bool:
    """Would this grant let the call through on its own terms (limits and ceiling)?"""
    return taint_rank(call.provenance) <= taint_rank(max_taint) and _within_limits(
        constraints, call
    )


def _replay(
    constraints: dict[str, Any],
    max_taint: str,
    benign: list[ObservedCall],
    held: list[ObservedCall],
    flagged: list[ObservedCall],
) -> tuple[dict[str, Any], bool]:
    """Replay the recorded calls against the proposed grant. The proof passes when every
    benign call goes through. Held calls did not shape the limits; how many fall
    inside them, and how many the ceiling still escalates, is reported alongside."""
    allowed = [c for c in benign if _passes(constraints, max_taint, c)]
    held_within = [c for c in held if _within_limits(constraints, c)]
    held_escalated = [c for c in held if taint_rank(c.provenance) > taint_rank(max_taint)]
    flagged_refused = [c for c in flagged if not _passes(constraints, max_taint, c)]
    proof = {
        "method": "replay of the recorded calls against the proposed grant",
        "benign_calls": len(benign),
        "benign_calls_allowed": len(allowed),
        "held_calls": len(held),
        "held_calls_within_limits": len(held_within),
        "held_calls_still_escalated_by_the_ceiling": len(held_escalated),
        "flagged_calls": len(flagged),
        "flagged_calls_the_grant_alone_would_refuse": len(flagged_refused),
        "decision_ids": [c.decision_id for c in [*benign, *held]][:50],
    }
    return proof, len(allowed) == len(benign)


def _grant_title(agent: str, tool_key: str, limits: list[Limit], max_taint: str, n: int) -> str:
    title = f"Let {agent} call {tool_key}"
    if limits:
        title += " with " + " and ".join(lim.phrase for lim in limits)
    if taint_rank(max_taint) > taint_rank("user"):
        title += f", using values from {_TAINT_PHRASE.get(max_taint, max_taint)}"
    seen = [f"seen {n} time{'s' if n != 1 else ''}"]
    numeric = [lim for lim in limits if lim.seen]
    if len(numeric) == 1:
        seen.append(numeric[0].seen)
    else:
        seen += [f"{lim.seen.replace('max ', f'max {lim.path} ')}" for lim in numeric]
    return f"{title} ({', '.join(seen)})"


def propose_from_traffic(
    session: Session,
    *,
    agent: str | None = None,
    since: dt.datetime | None = None,
    days: int | None = 30,
) -> TrafficReport:
    """File ``tool.declare`` and ``capability.grant`` proposals from observed tool calls.

    ``since`` wins over ``days``; ``days=None`` with no ``since`` reads all traffic.
    Nothing is applied. Re-running refreshes open proposals rather than duplicating
    them, and supersedes undecided ones the traffic has moved past.
    """
    report = TrafficReport()
    if since is None and days is not None:
        since = utcnow() - dt.timedelta(days=days)

    calls = observed_calls(session, agent=agent, since=since)
    for call in calls:
        report.calls[call.verdict] = report.calls.get(call.verdict, 0) + 1

    by_pair: dict[tuple[str, str], list[ObservedCall]] = defaultdict(list)
    for call in calls:
        by_pair[(call.agent, call.tool_key)].append(call)

    # Lineage sees calls that never reached a decision (OTel ingestion, another
    # gateway). Nothing about their arguments or provenance is known, so they can name
    # an undeclared tool but cannot justify a grant.
    lineage_only: dict[tuple[str, str], int] = {}
    edges = select(LineageEdge).where(
        LineageEdge.relation == "calls_tool", LineageEdge.src_type == "agent"
    )
    if agent is not None:
        edges = edges.where(LineageEdge.src_id == agent)
    if since is not None:
        edges = edges.where(LineageEdge.last_observed_at >= since)
    for edge in session.scalars(edges):
        if (edge.src_id, edge.dst_id) not in by_pair:
            lineage_only[(edge.src_id, edge.dst_id)] = int(edge.observed_count or 0)
    for (slug, tool_key), count in sorted(lineage_only.items()):
        report.skipped.append(
            {
                "agent": slug,
                "tool_key": tool_key,
                "reason": f"seen {count} time(s) in lineage with no recorded decision, so "
                "there are no arguments or provenance to learn a grant from",
            }
        )

    # --- tool.declare ----------------------------------------------------------
    declared = set(session.scalars(select(Tool.key)))
    seen_tools: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for call in calls:
        seen_tools[call.tool_key][call.agent] += 1
    for (slug, tool_key), count in lineage_only.items():
        seen_tools[tool_key][slug] += max(count, 1)
    for tool_key in sorted(seen_tools):
        if tool_key in declared:
            continue
        impact = infer_declared_impact(tool_key)
        by_agent = dict(seen_tools[tool_key])
        total = sum(by_agent.values())
        who = ", ".join(sorted(by_agent))
        _file(
            session,
            report,
            kind=DECLARE_KIND,
            agent="*",
            tool_key=tool_key,
            scope_level="org",
            scope_id="*",
            target_type="tool",
            title=(
                f"Declare {tool_key} as {_IMPACT_PHRASE[impact]} (called {total} "
                f"time{'s' if total != 1 else ''} by {who}, never declared; impact "
                "guessed from its name)"
            ),
            rationale=(
                "An undeclared tool is escalated on every call and reasoned about as if it "
                "only read something. The impact here is a guess from the tool's name — "
                "check it: a tool that moves money or sends a message is irreversible."
            ),
            diff={"tool_key": tool_key, "impact": impact, "output_trust": "untrusted"},
            evidence={"calls_by_agent": by_agent, "impact_inferred_from": "name"},
            expected_effect={"removes": "tool.not_declared", "calls_seen": total},
            proof={
                "method": "the tool is still undeclared, and was called in the window",
                "calls_seen": total,
                "impact_inferred_from": "name",
            },
            proof_passed=True,
        )

    # --- capability.grant ------------------------------------------------------
    for (slug, tool_key), pair_calls in sorted(by_pair.items()):
        benign = [c for c in pair_calls if c.verdict == "benign"]
        held = [c for c in pair_calls if c.verdict == "held"]
        flagged = [c for c in pair_calls if c.verdict == "flagged"]
        where = {"agent": slug, "tool_key": tool_key}
        existing = _matching_grant(_live_grants(session, slug), tool_key)
        # Once a grant exists, what was held or flagged before it is history: those
        # calls can no longer reach the approval queue, so repeating them every run
        # is noise. Report what happened under the grant in force.
        granted_at = as_aware(existing.created_at) if existing is not None else None
        recent_held = [c for c in held if granted_at is None or (c.at or granted_at) >= granted_at]
        recent_flagged = [
            c for c in flagged if granted_at is None or (c.at or granted_at) >= granted_at
        ]
        if recent_held:
            reasons = sorted({c.why for c in recent_held})
            hint = ""
            if any("composition.escalation" in r for r in reasons):
                # Composition blocks rather than escalates, so there is no approval to
                # give; the flow is either an attack or a source someone should trust.
                hint = (
                    " composition.escalation blocks rather than escalating, so nothing "
                    "reaches the queue: if the value came from an internal system of record, "
                    "declare that tool's output trusted (`agentfox declare tool <tool> "
                    "--impact read --output-trust trusted`)."
                )
            report.skipped.append(
                {
                    **where,
                    "reason": f"{len(recent_held)} call(s) carried untrusted provenance nobody "
                    f"approved ({', '.join(reasons)}). An injected call looks like this, so they "
                    "shape neither the limits nor the provenance ceiling; with a grant in "
                    "place, calls like them are escalated to the approval queue, and "
                    f"approving them there is what lets them count.{hint}",
                }
            )
        if recent_flagged:
            report.skipped.append(
                {
                    **where,
                    "reason": f"{len(recent_flagged)} call(s) flagged and never learned from "
                    f"({'; '.join(sorted({c.why for c in recent_flagged}))})",
                }
            )
        learnable = benign + held
        if not learnable:
            continue

        # The ceiling and the limits come from benign calls only. A held call is what
        # an injected call looks like, so its values never become a limit until a
        # person approves calls like it (which makes them benign).
        max_taint = _worst(["user", *(c.provenance for c in benign)])
        evidence = {
            "benign_calls": len(benign),
            "held_calls": len(held),
            "flagged_calls": len(flagged),
            "provenance_seen": sorted({c.provenance for c in benign}),
            "approved_by_a_person": sum(1 for c in benign if c.approved),
        }

        if existing is not None:
            if all(_passes(existing.constraints_json or {}, existing.max_taint, c) for c in benign):
                report.skipped.append(
                    {**where, "reason": f"already granted ({existing.id}); nothing new to learn"}
                )
                continue
            if existing.tool_key != tool_key or taint_rank(max_taint) <= taint_rank(
                existing.max_taint
            ):
                report.skipped.append(
                    {
                        **where,
                        "reason": f"covered by grant {existing.id} ('{existing.tool_key}'), "
                        "which these calls exceed in a way traffic cannot justify widening; "
                        "change it by hand",
                    }
                )
                continue
            # The only way benign traffic exceeds an existing grant is its provenance
            # ceiling: a call over a declared limit is flagged, never benign.
            constraints = dict(existing.constraints_json or {})
            proof, passed = _replay(constraints, max_taint, benign, [], held + flagged)
            approved = sum(
                1
                for c in benign
                if c.approved and taint_rank(c.provenance) > taint_rank(existing.max_taint)
            )
            _file(
                session,
                report,
                kind=GRANT_KIND,
                agent=slug,
                tool_key=tool_key,
                scope_level="agent",
                scope_id=slug,
                target_type="capability",
                title=(
                    f"Let {slug} call {tool_key} using values from "
                    f"{_TAINT_PHRASE.get(max_taint, max_taint)} ({approved} such "
                    f"call{'s' if approved != 1 else ''} approved by a person)"
                ),
                rationale=(
                    f"{slug} already holds this grant at provenance '{existing.max_taint}'. "
                    f"Calls carrying '{max_taint}' were escalated and a person approved them; "
                    "this raises the grant's ceiling so the next one is not escalated."
                ),
                diff={
                    "agent": slug,
                    "tool_key": tool_key,
                    "replaces": existing.id,
                    "from_max_taint": existing.max_taint,
                    "max_taint": max_taint,
                },
                evidence=evidence,
                expected_effect={"benign_calls_allowed": proof["benign_calls_allowed"]},
                proof=proof,
                proof_passed=passed,
            )
            continue

        limits = suggest_limits([c.arguments for c in benign]) if benign else []
        constraints = {lim.path: lim.spec for lim in limits}
        proof, passed = _replay(constraints, max_taint, benign, held, flagged)
        rationale = (
            f"{slug} called {tool_key} {len(pair_calls)} time(s) in the window; "
            f"{len(benign)} were refused only for configuration (no grant, an undeclared "
            "tool) or were approved by a person. The limits are read off those calls."
        )
        if not benign:
            rationale += (
                " None were, so there are no limits to read: this grant names the tool "
                "only. Add limits by hand before approving if the tool takes amounts or "
                "recipients."
            )
        if held:
            rationale += (
                f" {len(held)} of them carried untrusted provenance nobody has approved; they "
                f"shaped neither the limits nor the ceiling, which stays at '{max_taint}', so "
                "calls like them are still escalated. Approve them as they arrive and the "
                "next run proposes raising it."
            )
        _file(
            session,
            report,
            kind=GRANT_KIND,
            agent=slug,
            tool_key=tool_key,
            scope_level="agent",
            scope_id=slug,
            target_type="capability",
            title=_grant_title(slug, tool_key, limits, max_taint, len(learnable)),
            rationale=rationale,
            diff={
                "agent": slug,
                "tool_key": tool_key,
                "actions": ["*"],
                "constraints": constraints,
                "max_taint": max_taint,
                "requires_approval": False,
            },
            evidence={
                **evidence,
                "limits": [{"path": lim.path, "seen": lim.seen or lim.phrase} for lim in limits],
            },
            expected_effect={
                "benign_calls_allowed": proof["benign_calls_allowed"],
                "held_calls_still_escalated": proof["held_calls_still_escalated_by_the_ceiling"],
            },
            proof=proof,
            proof_passed=passed,
        )

    report.verified += _verify_applied(session)
    return report


def _verify_applied(session: Session) -> list[str]:
    """An applied grant the agent has since used without a capability refusal did what
    it promised. Anything else is left for a person: a refusal after the grant could as
    easily be an attack it correctly stopped as a limit set too tight."""
    out: list[str] = []
    slugs = {a.id: a.slug for a in session.scalars(select(Agent))}
    refusals = {"capability.denied", "capability.default_deny", "capability.constraint_violated"}
    for proposal in session.scalars(
        select(ChangeProposal).where(
            ChangeProposal.kind == GRANT_KIND,
            ChangeProposal.source == SOURCE,
            ChangeProposal.status == contract.APPLIED,
        )
    ):
        diff = proposal.diff_json or {}
        applied_at = as_aware(proposal.applied_at)
        if applied_at is None:
            continue
        since_applied = [
            d
            for d in session.scalars(
                select(Decision).where(
                    Decision.surface == "tool_args",
                    Decision.tool_key == diff.get("tool_key"),
                    Decision.created_at >= applied_at,
                )
            )
            if slugs.get(d.agent_id or "") == diff.get("agent")
        ]
        if not since_applied:
            continue
        if any(
            {str(r.get("rule_id")) for r in d.rules_fired_json or []} & refusals
            for d in since_applied
        ):
            continue
        verify_proposal(
            session,
            proposal,
            verified=True,
            note=(
                f"{len(since_applied)} call(s) since it was applied, none refused at the "
                "capability layer"
            ),
        )
        out.append(proposal.id)
    return out


def parse_since(text: str | None) -> dt.datetime | None:
    """``7d``, ``24h``, ``30m`` or an ISO date/time. None for None."""
    if not text:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*([dhm])\s*", text)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        delta = {"d": dt.timedelta(days=amount), "h": dt.timedelta(hours=amount)}.get(
            unit, dt.timedelta(minutes=amount)
        )
        return utcnow() - delta
    try:
        parsed = dt.datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValueError(
            f"'{text}' is not a window: use 7d, 24h, 30m or an ISO date like 2026-10-01"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


__all__ = [
    "CONFIGURATION_RULES",
    "DECLARE_KIND",
    "GRANT_KIND",
    "PROVENANCE_RULES",
    "SOURCE",
    "TrafficReport",
    "classify",
    "infer_declared_impact",
    "nice_ceiling",
    "observed_calls",
    "parse_since",
    "propose_from_traffic",
    "suggest_limits",
]
