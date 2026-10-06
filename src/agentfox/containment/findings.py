"""Containment findings — a refused action, named by what actually refused it.

The controls that are supposed to hold *after* a detector has been fooled — the
capability grant, argument provenance, composition, blast radius — set the verdict,
and each needs a finding of its own. Titling the finding after whichever detector
happened to fire on the same call ("Blocked on tool_args: PII.EMAIL" for a call
that default-deny and a taint rule refused) would tell a reader the product blocked
an email address, when it stopped an exfiltration attempt.

So a rule that did not test detections is a cause in its own right, and the
finding for it says, in one sentence, who tried to do what with which data and
what happened:

    support-bot tried to send_email with data that came from a web page (contained)

One finding per (agent, tool, rule), counted on recurrence through the shared
``raise_finding`` fingerprint, exactly as detector findings are.

``CAUSES`` is also the vocabulary ``agentfox report`` groups by, so the report and
the findings queue cannot describe the same refusal two different ways.
"""

from __future__ import annotations

import re
from typing import Any

from agentfox.core.vocab import EFFECT_RANK, taint_rank
from agentfox.detection.composition import tool_key_from_origin

#: The finding type. Distinct from ``guardrail_detection`` on purpose: a detector
#: catch and a containment refusal are triaged differently — the first asks "was the
#: detector right", the second asks "why did the agent try that".
FINDING_TYPE = "containment"

#: Effects that change what an action may do. Redaction rewrites content and is a
#: detector's business; these stop or hold the action itself.
_CONTAINING_EFFECTS = ("block", "escalate")

#: cause key -> the label a reader sees when refusals are counted by cause.
CAUSES: dict[str, str] = {
    "untrusted_data": "Data from an untrusted source",
    "composition": "Output of one tool fed into a riskier one",
    "no_permission": "No permission for the tool",
    "limit_exceeded": "Outside the limits of its permission",
    "approval_required": "Needs a person's sign-off",
    "destructive": "Destructive or over-broad action",
    "blast_radius": "Knock-on effects too wide",
    "data_scope": "Data access not scoped to the caller",
    "credentials": "Credentials at risk",
    "unknown_tool": "A tool nobody has declared",
    "no_intent": "Irreversible action with no stated task",
    "runaway": "Budget or loop limit",
    "tamper": "Attempt to switch off governance",
    "unverified_completion": "Claimed done without checking",
    "fail_closed": "Safety checks unavailable",
    "business_rule": "Business rule",
    "policy": "Other policy rule",
}

#: Rule-id prefixes, most specific first. Matched with ``startswith``.
_CAUSE_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("taint.", "untrusted_data"),
    ("composition.", "composition"),
    ("capability.denied", "no_permission"),
    ("capability.default_deny", "no_permission"),
    ("capability.constraint_violated", "limit_exceeded"),
    ("capability.approval_required", "approval_required"),
    ("capability.requires_approval", "approval_required"),
    ("eu.art14", "approval_required"),
    ("cascade.", "blast_radius"),
    ("access.", "data_scope"),
    ("secrets.", "credentials"),
    ("control_plane.", "tamper"),
    ("tool.not_declared", "unknown_tool"),
    ("intent.", "no_intent"),
    ("budget.", "runaway"),
    ("loop.", "runaway"),
    ("completion.", "unverified_completion"),
    ("pipeline.fail_closed", "fail_closed"),
    ("business.", "business_rule"),
    ("sql.", "destructive"),
    ("shell.", "destructive"),
    ("scope.", "destructive"),
    ("action.", "destructive"),
    ("http.", "destructive"),
)

#: Where an argument's data came from, in words. Keys are taint sources.
_SOURCE_WORDS = {
    "retrieved": "a retrieved document or web page",
    "tool_result": "another tool's output",
    "subagent": "another agent",
    "memory": "the agent's stored memory",
}

#: A tool whose output is, in practice, a web page. Only used to choose the noun.
_WEB_TOOL = re.compile(r"web|fetch|brows|http|url|scrape|crawl|page|site", re.I)


def is_detector_rule(rule: dict[str, Any]) -> bool:
    """A rule whose condition tested detections — its verdict is a detector's."""
    return bool(rule.get("entities") or rule.get("entity_prefixes"))


def cause_of(rule_id: str) -> str:
    for prefix, cause in _CAUSE_BY_PREFIX:
        if rule_id.startswith(prefix):
            return cause
    return "policy"


def containment_rules(rules_fired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The fired rules that stopped or held an action without testing detections."""
    return [
        r for r in rules_fired if r.get("effect") in _CONTAINING_EFFECTS and not is_detector_rule(r)
    ]


def detector_verdict(rules_fired: list[dict[str, Any]]) -> tuple[str, str]:
    """``(effective, applied)`` counting detector rules only.

    The decision's own verdict is the maximum over every rule, so on a call that a
    capability rule blocked it says "block" whatever the detectors thought. A
    detection finding has to report what the *detector* rules did, and nothing else.
    """
    effective, applied = "allow", "allow"
    for rule in rules_fired:
        if not is_detector_rule(rule):
            continue
        effect = rule.get("effect") or "allow"
        if EFFECT_RANK.get(effect, 0) > EFFECT_RANK.get(effective, 0):
            effective = effect
        if rule.get("mode", "enforce") == "enforce" and EFFECT_RANK.get(
            effect, 0
        ) > EFFECT_RANK.get(applied, 0):
            applied = effect
    return effective, applied


def matches_detector_rule(entity_type: str, rules_fired: list[dict[str, Any]]) -> bool:
    """Whether a detection is one a firing, non-allow detector rule was about."""
    entity = (entity_type or "").upper()
    for rule in rules_fired:
        if not is_detector_rule(rule) or rule.get("effect") in (None, "allow"):
            continue
        if entity in (rule.get("entities") or []):
            return True
        if any(entity.startswith(p) for p in rule.get("entity_prefixes") or []):
            return True
    return False


def untrusted_source(
    argument_taint: dict[str, str] | None,
    propagated_from: dict[str, str] | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """``(source, origin_tool, paths)`` for the least-trusted argument.

    ``origin_tool`` is the tool whose output an argument was copied from, when the
    tracker knows it — the difference between "another tool's output" and "a web
    page (fetch_url)".
    """
    worst: str | None = None
    for source in (argument_taint or {}).values():
        if source in _SOURCE_WORDS and (worst is None or taint_rank(source) > taint_rank(worst)):
            worst = source
    if worst is None:
        return None, None, []
    paths = sorted(p for p, s in (argument_taint or {}).items() if s == worst)
    raw = next((propagated_from[p] for p in paths if (propagated_from or {}).get(p)), None)
    # The tracker records where a value was copied from as a path; only a tool is
    # worth naming, and only by its key.
    origin = tool_key_from_origin(raw) if raw else None
    return worst, origin, paths


def source_words(source: str | None, origin_tool: str | None) -> str:
    if origin_tool:
        if _WEB_TOOL.search(origin_tool):
            return f"a web page ({origin_tool})"
        return f"the output of {origin_tool}"
    if source == "retrieved":
        return "a retrieved document or web page"
    return _SOURCE_WORDS.get(source or "", "an untrusted source")


def outcome_words(effect: str, applied: bool) -> str:
    if not applied:
        return "would have been " + ("held for approval" if effect == "escalate" else "contained")
    return "held for approval" if effect == "escalate" else "contained"


def _clip(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    # A rule's reason is often a sentence and a qualification; the sentence is the story.
    text = re.split(r";|, and ", text, maxsplit=1)[0]
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def story(
    *,
    agent: str | None,
    tool: str | None,
    rule: dict[str, Any],
    applied: bool,
    source: str | None = None,
    origin_tool: str | None = None,
    decision_verdict: str | None = None,
) -> str:
    """One plain-English sentence: who tried what, why it was stopped, and what happened."""
    who = agent or "An unregistered agent"
    what = tool or "act"
    rule_id = str(rule.get("rule_id") or "")
    cause = cause_of(rule_id)
    evidence = rule.get("evidence") or {}
    # What happened to the call is the decision's verdict, not this rule's effect: a
    # taint rule that asked for approval on a call another rule blocked outright was
    # contained, not held.
    effect = str(rule.get("effect") or "block")
    if applied and decision_verdict in _CONTAINING_EFFECTS:
        effect = decision_verdict
    outcome = outcome_words(effect, applied)

    if cause == "untrusted_data":
        body = f"tried to {what} with data that came from {source_words(source, origin_tool)}"
    elif cause == "composition":
        origin = evidence.get("origin_tool") or origin_tool
        body = (
            f"tried to pass the output of {origin} into {what}, a higher-impact action"
            if origin
            else f"tried to feed one tool's output into {what}, a higher-impact action"
        )
    elif cause == "no_permission":
        body = f"tried to {what} without permission to use it"
    elif cause == "limit_exceeded":
        body = f"tried to {what} outside the limits of its permission"
    elif cause == "approval_required":
        body = f"tried to {what}, which needs a person's sign-off first"
    elif cause == "blast_radius":
        body = f"tried to {what}, which sets off a chain of downstream effects"
    elif cause == "data_scope":
        body = f"tried to {what} with a query not limited to the caller's own records"
    elif cause == "credentials":
        body = f"tried to {what} in a way that touches stored credentials"
    elif cause == "unknown_tool":
        body = f"called {what}, a tool nobody has declared"
    elif cause == "no_intent":
        body = f"tried an irreversible action ({what}) with no stated task"
    elif cause == "runaway":
        body = f"hit its budget or loop limit calling {what}"
    elif cause == "tamper":
        body = "tried to switch off the controls that govern it"
    elif cause == "unverified_completion":
        body = "claimed a task was finished without checking the work landed"
    elif cause == "fail_closed":
        body = f"tried to {what} while safety checks were unavailable"
    elif cause == "destructive":
        detail = _clip(str(rule.get("reason") or ""), 90)
        body = f"tried a destructive or over-broad {what} call" + (f": {detail}" if detail else "")
    else:
        detail = _clip(str(rule.get("reason") or rule_id), 90)
        body = f"tried to {what}, stopped by a policy rule: {detail}"
    return f"{who} {body} ({outcome})"


def rule_applied(
    rule: dict[str, Any],
    decision_verdict: str,
    scope: tuple[str, frozenset[str]] = ("enforced", frozenset()),
) -> bool:
    """Whether this rule's effect actually stopped the call.

    Its own mode was enforce AND the decision went that way — unless the caller let
    the call run anyway (``scope``: a dry run or auto() in observe mode is
    ``"none"``; a rule the caller exempts), and except that strict
    auto(mode="enforce") stops on any rule that fired (``"all"``). Findings and the
    one-page report both ask this, so they never disagree about what was contained.
    """
    in_process, exempt = scope
    if in_process == "none" or str(rule.get("rule_id") or "") in exempt:
        return False
    if in_process == "all":
        return True
    return rule.get("mode", "enforce") == "enforce" and decision_verdict != "allow"


def decision_scope(taint_summary: dict[str, Any] | None) -> tuple[str, frozenset[str]]:
    """The caller's in-process scope as the enforcer recorded it on the decision."""
    summary = taint_summary or {}
    return (
        str(summary.get("in_process") or "enforced"),
        frozenset(summary.get("exempt_rules") or ()),
    )


def raise_containment_findings(
    session: Any,
    *,
    agent: Any,
    tool_key: str | None,
    surface: str,
    rules_fired: list[dict[str, Any]],
    argument_taint: dict[str, str] | None,
    argument_propagated_from: dict[str, str] | None,
    trace_id: str | None,
    decision_id: str | None,
    decision_verdict: str,
    scope: tuple[str, frozenset[str]] = ("enforced", frozenset()),
) -> int:
    """One finding per (agent, tool, rule) that stopped or held this call. Returns count."""
    from agentfox.prove.findings import raise_finding

    rules = containment_rules(rules_fired)
    if not rules:
        return 0
    source, origin, paths = untrusted_source(argument_taint, argument_propagated_from)
    slug = getattr(agent, "slug", None)
    raised = 0
    seen: set[str] = set()
    for rule in rules:
        rule_id = str(rule.get("rule_id") or "")
        if rule_id in seen:
            continue
        seen.add(rule_id)
        applied = rule_applied(rule, decision_verdict, scope)
        cause = cause_of(rule_id)
        severity = str(rule.get("severity") or ("high" if rule["effect"] == "block" else "medium"))
        raise_finding(
            session,
            type=FINDING_TYPE,
            severity=severity,
            title=story(
                agent=slug,
                tool=tool_key,
                rule=rule,
                applied=applied,
                source=source,
                origin_tool=origin,
                decision_verdict=decision_verdict,
            ),
            subject_type="agent",
            subject_id=getattr(agent, "id", None),
            # Applied and would-have-been are different problems: the first is a
            # control working, the second is an exposure. Keyed apart so promoting a
            # policy to enforce starts a new count rather than relabelling the old.
            fingerprint_parts=(tool_key or surface, rule_id, applied),
            evidence={
                "trace_id": trace_id,
                "decision_id": decision_id,
                "surface": surface,
                "tool": tool_key,
                "rule_id": rule_id,
                "effect": rule.get("effect"),
                "applied": applied,
                "cause": cause,
                "cause_label": CAUSES.get(cause, CAUSES["policy"]),
                "reason": rule.get("reason"),
                "untrusted_source": source,
                "origin_tool": origin,
                "untrusted_arguments": paths,
            },
            control_keys=list(rule.get("controls") or []),
        )
        raised += 1
    return raised


__all__ = [
    "CAUSES",
    "FINDING_TYPE",
    "cause_of",
    "containment_rules",
    "detector_verdict",
    "is_detector_rule",
    "matches_detector_rule",
    "outcome_words",
    "raise_containment_findings",
    "source_words",
    "story",
    "untrusted_source",
]
