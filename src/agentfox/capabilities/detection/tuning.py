"""The guardrail tuning surface.

Detection is commoditised. Every vendor and every OSS project can tell you that a
string contains an SSN. What none of them solve, and what the practitioner evidence
kept returning to, is what happens **after** a detector fires:

* **Violation specificity.** "Blocked by policy" is not an explanation. An
  engineer holding that message cannot tell whether the guardrail was right, and the
  cheapest way to make the error go away is to disable the detector. So every verdict
  can produce the detector, the rule, the matched span, the score against the
  threshold that decided it, and the concrete next action.
* **Cumulative latency budgeting.** The per-call budget is honest but incomplete:
  one request evaluates several messages, the output, and every tool call, so a
  stack that respects a 100 ms per-call budget can still spend 600 ms on a request.
  The ledger below is per-*request*, and later surfaces shed expensive detectors once
  it is exhausted rather than quietly blowing the SLO.
* **False-positive loop.** A team with no route for "this was wrong" turns the
  detector off. Feedback is recorded against the decision, aggregated into per-detector
  precision, and turned into a threshold recommendation — or, importantly, into an
  honest "these scores do not separate, no threshold fixes this".

The suppressions this produces **expire**. A permanent silent exception is
indistinguishable from a detector that stopped working, and that is how guardrail
programmes decay.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import statistics
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.detection.base import Detection
from agentfox.core.models import (
    Agent,
    Decision,
    DetectionFinding,
    DetectorRun,
    GuardrailFeedback,
    Suppression,
    Trace,
)
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.operator_log import record

LABELS = ("false_positive", "true_positive", "false_negative")
SUPPRESSION_SCOPES = ("agent", "global")

# Below this many labelled false positives a "recommendation" is numerology. We say so
# rather than emitting a confident number off three data points.
MIN_LABELS_FOR_RECOMMENDATION = 5


# ---------------------------------------------------------------------------
# Violation specificity
# ---------------------------------------------------------------------------


def _excerpt(content: str, start: int, end: int, window: int = 24) -> str:
    """Locate the match in context without reproducing the sensitive value itself.

    We show the surroundings and the shape of the match, never the match. An
    explanation that re-leaks the secret it blocked is not an improvement.
    """
    if not content or end <= start:
        return ""
    left = content[max(0, start - window) : start]
    right = content[end : end + window]
    return f"…{left}[{'•' * min(end - start, 12)}]{right}…"


@dataclass
class Match:
    detector: str
    entity_type: str
    start: int
    end: int
    score: float
    excerpt: str = ""
    owasp_id: str | None = None
    decisive: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "entity_type": self.entity_type,
            "span": [self.start, self.end],
            "score": round(self.score, 3),
            "excerpt": self.excerpt,
            "owasp_id": self.owasp_id,
            "decisive": self.decisive,
        }


@dataclass
class Explanation:
    """Everything needed to agree or disagree with a verdict, in one object."""

    verdict: str
    effective_verdict: str
    mode: str
    summary: str
    surface: str
    trace_id: str | None = None
    decision_id: str | None = None
    rule: dict[str, Any] | None = None
    matches: list[Match] = field(default_factory=list)
    detectors: list[dict[str, Any]] = field(default_factory=list)
    remedy: str = ""
    dispute: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "effective_verdict": self.effective_verdict,
            "mode": self.mode,
            "summary": self.summary,
            "surface": self.surface,
            "trace_id": self.trace_id,
            "decision_id": self.decision_id,
            "rule": self.rule,
            "matches": [m.to_json() for m in self.matches],
            "detectors": self.detectors,
            "remedy": self.remedy,
            "dispute": self.dispute,
        }


_REMEDY = {
    "PII": (
        "Remove or tokenise the personal data before the call, or scope a policy "
        "exception for this agent if the surface is permitted to carry it."
    ),
    "SECRET": (
        "Rotate the exposed credential — it has been in a prompt and must be treated "
        "as compromised — then remove it from the payload."
    ),
    "INJECTION": (
        "The instruction arrived in untrusted content. Fix the source, or lower the "
        "capability ceiling for arguments derived from it rather than relaxing the detector."
    ),
    "SCHEMA": "The output did not satisfy the declared schema. Fix the schema or the prompt.",
    "SAFETY": "Content matched the safety lexicon. Review the sample before relaxing anything.",
}

#: The injection remedy for the user's own message. "Untrusted content" is the
#: indirect-injection story (a document, a tool result); on the input surface the
#: instruction came from the person typing, and the fix is a different one.
_INPUT_INJECTION_REMEDY = (
    "The instruction arrived in the user's own message (a direct injection attempt). "
    "Keep the block, or narrow what this agent may do on that user's behalf; if the "
    "message was legitimate, file it as a false positive rather than relaxing the "
    "detector."
)


def _remedy_for(entity_types: list[str], surface: str | None = None) -> str:
    for entity in entity_types:
        for prefix, text in _REMEDY.items():
            if entity.upper().startswith(prefix):
                if prefix == "INJECTION" and surface == "input":
                    return _INPUT_INJECTION_REMEDY
                return text
    return (
        "Review the matched span against the rule. If the rule is right and the content "
        "is wrong, fix the content; if the rule is wrong, file it as a false positive "
        "rather than disabling the detector."
    )


def _names(exact: set[str], prefixes: tuple[str, ...], entity_type: str) -> bool:
    """Whether a rule naming these entities is about a detection of `entity_type`.

    The same two operations the policy engine applies — equality for `entity`,
    `startswith` for `entity_prefix` — so this cannot drift from what actually
    fired. Neither given means the rule has no entity constraint, so everything is
    relevant.
    """
    if not exact and not prefixes:
        return True
    actual = entity_type.upper()
    if actual in exact:
        return True
    return bool(prefixes) and actual.startswith(prefixes)


def explain(
    result: Any,
    pipeline_result: Any,
    *,
    content: str = "",
    surface: str = "input",
    thresholds: dict[str, float] | None = None,
) -> Explanation:
    """Turn a verdict into something an engineer can act on or argue with."""
    thresholds = thresholds or {}
    rule = next(
        (r for r in result.rules_fired if r.get("effect") == result.effective_verdict),
        result.rules_fired[0] if result.rules_fired else None,
    )

    # The decisive detection is the highest-scoring one among the entity types the
    # winning rule actually names — not simply the highest-scoring one overall, which
    # would credit a detector that had no bearing on the outcome.
    #
    # This was already the intent, and it did not work, because nothing populated
    # `entities`: `FiredRule.to_json()` dropped the rule's detection condition, so
    # `named` was always empty and every explanation fell through to highest-score.
    # On an injection payload carrying the attacker's own address, `PII.EMAIL` at
    # 0.90 beat `INJECTION.INSTRUCTION_OVERRIDE` at 0.85 and the summary read
    # "block on input: PII.EMAIL ... which rule `injection.direct` treats as block".
    # The rule and the match named in one sentence had nothing to do with each other.
    exact = {str(e).upper() for e in (rule or {}).get("entities", []) or []}
    prefixes = tuple(str(e).upper() for e in (rule or {}).get("entity_prefixes", []) or [])
    candidates = list(getattr(pipeline_result, "detections", []) or [])
    relevant = [d for d in candidates if _names(exact, prefixes, d.entity_type)]
    # Falling back to every candidate when the rule names entities none of which were
    # detected: the rule fired on something other than a detection (a tool, a
    # capability, taint), so the best available answer is the strongest signal there
    # was. An explanation with no match at all explains less than an imperfect one.
    decisive = max(relevant or candidates, key=lambda d: d.score, default=None)

    matches: list[Match] = []
    for detector_result in getattr(pipeline_result, "results", []) or []:
        for detection in detector_result.detections:
            matches.append(
                Match(
                    detector=detector_result.detector_key,
                    entity_type=detection.entity_type,
                    start=detection.start,
                    end=detection.end,
                    score=detection.score,
                    excerpt=_excerpt(content, detection.start, detection.end),
                    owasp_id=detection.owasp_id,
                    decisive=detection is decisive,
                )
            )

    detectors = [
        {
            "key": r.detector_key,
            "version": r.version,
            "score": round(r.score, 3),
            "threshold": thresholds.get(r.detector_key),
            "status": r.status,
            "duration_ms": round(r.duration_ms, 2),
            "matched": bool(r.detections),
        }
        for r in getattr(pipeline_result, "results", []) or []
    ]

    if decisive is not None:
        summary = (
            f"{result.effective_verdict} on {surface}: {decisive.entity_type} matched at "
            f"offset {decisive.start}–{decisive.end} with score {decisive.score:.2f}"
        )
        if rule:
            summary += f", which rule `{rule.get('rule_id')}` treats as {rule.get('effect')}"
    elif rule:
        summary = f"{result.effective_verdict} on {surface} by rule `{rule.get('rule_id')}`: " + (
            rule.get("reason") or "no detector match — the rule fired on context alone"
        )
    else:
        summary = f"{result.verdict} on {surface}: no rule fired"

    entity_types = [m.entity_type for m in matches if m.decisive] or [
        m.entity_type for m in matches
    ]
    # The dispute names the detector that produced the decisive match. Naming the first
    # match's detector instead filed the label against whichever detector happened to
    # run first — a false positive recorded against a detector that did nothing wrong,
    # which is precisely the input threshold tuning then acts on.
    decisive_detector = next((m.detector for m in matches if m.decisive), None)
    return Explanation(
        verdict=result.verdict,
        effective_verdict=result.effective_verdict,
        mode=result.mode,
        summary=summary,
        surface=surface,
        trace_id=result.trace_id,
        decision_id=result.decision_id,
        rule=rule,
        matches=matches,
        detectors=detectors,
        remedy=_remedy_for(entity_types, surface),
        dispute={
            "endpoint": "POST /api/guardrails/feedback",
            "payload": {
                "decision_id": result.decision_id,
                "label": "false_positive",
                "detector_key": decisive_detector,
                "entity_type": decisive.entity_type if decisive else None,
                "note": "why this was wrong",
            },
        },
    )


# ---------------------------------------------------------------------------
# Cumulative latency budgeting
# ---------------------------------------------------------------------------


@dataclass
class LedgerEntry:
    surface: str
    detector_key: str
    duration_ms: float
    status: str = "ok"


@dataclass
class LatencyLedger:
    """Per-*request* detector spend, across every surface the request touches.

    A per-call budget alone is a comfortable lie: one governed completion evaluates
    several messages, the output and every tool call, so a stack that never breaches
    100 ms per call can still cost half a second per request. The ledger is what makes
    the request-level number true.
    """

    budget_ms: float
    entries: list[LedgerEntry] = field(default_factory=list)

    @property
    def spent_ms(self) -> float:
        return sum(e.duration_ms for e in self.entries)

    def remaining_ms(self) -> float:
        return max(0.0, self.budget_ms - self.spent_ms)

    @property
    def exhausted(self) -> bool:
        return self.remaining_ms() <= 0.0

    def charge(self, pipeline_result: Any, surface: str) -> None:
        for r in getattr(pipeline_result, "results", []) or []:
            self.entries.append(
                LedgerEntry(
                    surface=surface,
                    detector_key=r.detector_key,
                    duration_ms=r.duration_ms,
                    status=r.status,
                )
            )

    def allowance_ms(self, per_call_ms: float) -> float:
        """What the next pipeline run may spend: the smaller of the two budgets."""
        return max(0.0, min(float(per_call_ms), self.remaining_ms()))

    def report(self) -> dict[str, Any]:
        per_detector: dict[str, float] = {}
        for entry in self.entries:
            per_detector[entry.detector_key] = (
                per_detector.get(entry.detector_key, 0.0) + entry.duration_ms
            )
        return {
            "budget_ms": round(self.budget_ms, 2),
            "spent_ms": round(self.spent_ms, 2),
            "remaining_ms": round(self.remaining_ms(), 2),
            "exhausted": self.exhausted,
            "surfaces_evaluated": len({e.surface for e in self.entries}),
            "per_detector_ms": {k: round(v, 2) for k, v in sorted(per_detector.items())},
        }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def latency_report(
    session: Session, *, agent_slug: str | None = None, days: int = 7
) -> dict[str, Any]:
    """Per-detector and per-agent latency, from what actually ran.

    Reported as p50/p95/max rather than a mean: a mean hides exactly the tail that
    gets a governance product removed for being slow.
    """
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    stmt = select(DetectorRun, Trace.agent_slug).join(
        Trace, Trace.id == DetectorRun.trace_id, isouter=True
    )
    stmt = stmt.where(DetectorRun.created_at >= since)
    if agent_slug:
        stmt = stmt.where(Trace.agent_slug == agent_slug)

    per_detector: dict[str, list[float]] = {}
    per_agent: dict[str, list[float]] = {}
    degraded = 0
    total = 0
    for run, slug in session.execute(stmt):
        total += 1
        per_detector.setdefault(run.detector_key, []).append(run.duration_ms)
        per_agent.setdefault(slug or "(unattributed)", []).append(run.duration_ms)
        if run.status in ("timeout", "skipped_budget"):
            degraded += 1

    def stats(values: list[float]) -> dict[str, Any]:
        return {
            "runs": len(values),
            "p50_ms": round(_percentile(values, 50), 2),
            "p95_ms": round(_percentile(values, 95), 2),
            "max_ms": round(max(values, default=0.0), 2),
            "total_ms": round(sum(values), 2),
        }

    return {
        "window_days": days,
        "runs": total,
        "degraded_runs": degraded,
        "degraded_rate": round(degraded / total, 4) if total else 0.0,
        "per_detector": {k: stats(v) for k, v in sorted(per_detector.items())},
        "per_agent": {k: stats(v) for k, v in sorted(per_agent.items())},
    }


# ---------------------------------------------------------------------------
# False-positive feedback loop
# ---------------------------------------------------------------------------


#: Roles whose labels do not shape detectors. An auditor's job is to observe the
#: control, and a control its auditor can tune is not independently audited.
LABEL_REFUSED_ROLES = frozenset({"auditor"})


def record_feedback(
    session: Session,
    *,
    decision_id: str,
    label: str,
    detector_key: str | None = None,
    entity_type: str | None = None,
    note: str = "",
    actor: str | None = None,
) -> GuardrailFeedback:
    """Record "this was wrong", attached to the decision it is about.

    Labels are the input precision reporting, threshold recommendations and the
    improvement loop all trust, so three rules hold here rather than at each caller:

    * **A label has an author.** ``actor`` is required and must be the authenticated
      identity — the HTTP route passes the signed-in user, never a body field.
    * **One label per decision per person.** Labelling the same decision again changes
      that person's label instead of adding a row; otherwise one insistent reviewer
      outvotes a team and a precision number becomes a measure of persistence.
    * **Every label is on the audit chain,** and a change records what it was before.
    """
    if label not in LABELS:
        raise ValueError(f"label must be one of {LABELS}")
    actor = (actor or "").strip()
    if not actor:
        raise ValueError("feedback needs the identity of the person filing it")
    decision = session.get(Decision, decision_id)
    if decision is None:
        raise ValueError("unknown decision")

    # Pull the score from the decision's own detector runs so precision is computed
    # against what actually fired, not against whatever the reporter typed.
    score = 0.0
    runs = list(
        session.scalars(select(DetectorRun).where(DetectorRun.id.in_(decision.detector_run_ids)))
    )
    matching = [r for r in runs if not detector_key or r.detector_key == detector_key]
    if matching:
        best = max(matching, key=lambda r: r.score)
        score = best.score
        detector_key = detector_key or best.detector_key
    if entity_type is None and decision.detector_run_ids:
        finding = session.scalar(
            select(DetectionFinding)
            .where(DetectionFinding.detector_run_id.in_(decision.detector_run_ids))
            .order_by(DetectionFinding.score.desc())
        )
        entity_type = finding.entity_type if finding else None
    # The label is about one entity, so its score is that entity's score. The run's
    # score is the max over everything the detector matched in the request: a label
    # on a 0.55 PII.EMAIL match in a run that also found a 0.95 PII.SSN would
    # otherwise be stored at 0.95, and a threshold recommendation fitted to these
    # labels would move by the wrong entity's confidence.
    if entity_type and matching:
        entity_match = session.scalar(
            select(DetectionFinding)
            .where(
                DetectionFinding.detector_run_id.in_([r.id for r in matching]),
                DetectionFinding.entity_type == entity_type,
            )
            .order_by(DetectionFinding.score.desc())
        )
        if entity_match is not None:
            score = entity_match.score
            detector_key = next(
                r.detector_key for r in matching if r.id == entity_match.detector_run_id
            )

    existing = session.scalar(
        select(GuardrailFeedback)
        .where(GuardrailFeedback.decision_id == decision_id, GuardrailFeedback.actor == actor)
        .order_by(GuardrailFeedback.created_at.desc(), GuardrailFeedback.id.desc())
        .limit(1)
    )
    if existing is not None:
        before = _feedback_state(existing)
        if existing.status == "applied" and existing.label != label:
            raise ValueError(
                "this label backs an applied suppression; revoke the suppression before "
                "changing the label it was granted on"
            )
        existing.label = label
        existing.detector_key = detector_key
        existing.entity_type = entity_type
        existing.score = score
        existing.verdict = decision.verdict
        existing.note = note
        session.flush()
        after = _feedback_state(existing)
        if after != before:
            chain.append(
                session,
                "guardrail.feedback.changed",
                actor_type="user",
                actor_id=actor,
                subject_type="decision",
                subject_id=decision_id,
                payload={"feedback_id": existing.id, "before": before, "after": after},
            )
        return existing

    feedback = GuardrailFeedback(
        decision_id=decision_id,
        trace_id=decision.trace_id,
        agent_id=decision.agent_id,
        detector_key=detector_key,
        entity_type=entity_type,
        label=label,
        score=score,
        verdict=decision.verdict,
        note=note,
        actor=actor,
    )
    session.add(feedback)
    session.flush()
    chain.append(
        session,
        "guardrail.feedback.recorded",
        actor_type="user",
        actor_id=actor,
        subject_type="decision",
        subject_id=decision_id,
        payload={"feedback_id": feedback.id, "after": _feedback_state(feedback)},
    )
    return feedback


def _feedback_state(row: GuardrailFeedback) -> dict[str, Any]:
    return {
        "label": row.label,
        "detector_key": row.detector_key,
        "entity_type": row.entity_type,
        "score": round(float(row.score or 0.0), 4),
        "note": row.note,
    }


def precision_report(
    session: Session, *, days: int = 30, agent_id: str | None = None
) -> dict[str, Any]:
    """Per-detector precision from human labels, with the label count next to it.

    The count is not decoration. Precision computed over four labels is noise, and
    presenting it without the denominator is how a tuning surface starts lying.
    """
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    stmt = select(GuardrailFeedback).where(GuardrailFeedback.created_at >= since)
    if agent_id:
        stmt = stmt.where(GuardrailFeedback.agent_id == agent_id)
    rows = list(session.scalars(stmt))
    per_detector: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.detector_key or "(unattributed)"
        bucket = per_detector.setdefault(
            key,
            {
                "labelled": 0,
                "false_positive": 0,
                "true_positive": 0,
                "false_negative": 0,
                "fp_scores": [],
                "tp_scores": [],
                "entities": {},
            },
        )
        bucket["labelled"] += 1
        bucket[row.label] = bucket.get(row.label, 0) + 1
        if row.label == "false_positive":
            bucket["fp_scores"].append(row.score)
        elif row.label == "true_positive":
            bucket["tp_scores"].append(row.score)
        if row.entity_type:
            bucket["entities"][row.entity_type] = bucket["entities"].get(row.entity_type, 0) + 1

    out: dict[str, Any] = {}
    for key, bucket in sorted(per_detector.items()):
        judged = bucket["false_positive"] + bucket["true_positive"]
        out[key] = {
            "labelled": bucket["labelled"],
            "false_positive": bucket["false_positive"],
            "true_positive": bucket["true_positive"],
            "false_negative": bucket["false_negative"],
            "precision": round(bucket["true_positive"] / judged, 3) if judged else None,
            "mean_fp_score": (
                round(statistics.fmean(bucket["fp_scores"]), 3) if bucket["fp_scores"] else None
            ),
            "mean_tp_score": (
                round(statistics.fmean(bucket["tp_scores"]), 3) if bucket["tp_scores"] else None
            ),
            "entities": dict(sorted(bucket["entities"].items())),
            "sufficient_sample": judged >= MIN_LABELS_FOR_RECOMMENDATION,
        }
    return {"window_days": days, "total_labels": len(rows), "detectors": out}


@dataclass
class Recommendation:
    detector_key: str
    action: str  # raise_threshold | no_clean_separation | insufficient_data | investigate
    suggested_threshold: float | None
    rationale: str
    false_positives_removed: int = 0
    true_positives_lost: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "detector_key": self.detector_key,
            "action": self.action,
            "suggested_threshold": self.suggested_threshold,
            "rationale": self.rationale,
            "false_positives_removed": self.false_positives_removed,
            "true_positives_lost": self.true_positives_lost,
        }


def threshold_recommendations(session: Session, *, days: int = 30) -> list[Recommendation]:
    """Turn labels into a threshold change — or into an honest refusal to suggest one.

    The interesting case is not the clean split. It is the detector whose false and
    true positives occupy the same score range, where no threshold helps and the real
    answer is a better detector. Saying so is more useful than a confident number.
    """
    report = precision_report(session, days=days)
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    rows = list(
        session.scalars(select(GuardrailFeedback).where(GuardrailFeedback.created_at >= since))
    )
    by_detector: dict[str, list[GuardrailFeedback]] = {}
    for row in rows:
        by_detector.setdefault(row.detector_key or "(unattributed)", []).append(row)

    out: list[Recommendation] = []
    for key, feedback in sorted(by_detector.items()):
        fps = [f.score for f in feedback if f.label == "false_positive"]
        tps = [f.score for f in feedback if f.label == "true_positive"]
        stats = report["detectors"].get(key, {})
        if not stats.get("sufficient_sample"):
            out.append(
                Recommendation(
                    key,
                    "insufficient_data",
                    None,
                    f"only {len(fps) + len(tps)} judged labels; "
                    f"{MIN_LABELS_FOR_RECOMMENDATION} needed before a threshold change is "
                    "anything but numerology",
                )
            )
            continue
        if not fps:
            out.append(
                Recommendation(
                    key, "investigate", None, "no false positives reported — nothing to tune"
                )
            )
            continue
        cutoff = max(fps)
        if tps and min(tps) <= cutoff:
            overlap = len([s for s in tps if s <= cutoff])
            out.append(
                Recommendation(
                    key,
                    "no_clean_separation",
                    None,
                    f"false positives score up to {cutoff:.2f} and {overlap} true positive(s) "
                    f"score at or below that. No threshold separates them — this needs a better "
                    f"detector or a narrower suppression, not a dial.",
                    false_positives_removed=0,
                    true_positives_lost=overlap,
                )
            )
            continue
        suggested = round(cutoff + 0.01, 3)
        out.append(
            Recommendation(
                key,
                "raise_threshold",
                suggested,
                f"all {len(fps)} reported false positives score at or below {cutoff:.2f}, and "
                f"every labelled true positive scores above it",
                false_positives_removed=len(fps),
                true_positives_lost=0,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Suppressions — scoped and expiring, never silent
# ---------------------------------------------------------------------------


def sample_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def apply_suppression(
    session: Session,
    *,
    feedback_id: str,
    scope: str = "agent",
    ttl_days: int = 30,
    actor: str | None = None,
    exact: bool = False,
    reason: str = "",
) -> Suppression:
    """Accept a false-positive report as a scoped, expiring exception.

    ``scope="agent"`` limits it to the agent that reported it, which is almost always
    right: a pattern that is noise for one agent is usually signal for another. A
    global suppression is possible but must be asked for.
    """
    if scope not in SUPPRESSION_SCOPES:
        # Reject rather than default to global, so a typo cannot silence a detector
        # for every agent in the tenant.
        raise ValueError(f"scope must be one of {SUPPRESSION_SCOPES}, got {scope!r}")
    feedback = session.get(GuardrailFeedback, feedback_id)
    if feedback is None:
        raise ValueError("unknown feedback")
    if feedback.label != "false_positive":
        raise ValueError("only a false positive can be suppressed")
    if not feedback.detector_key:
        raise ValueError("feedback has no detector to suppress")

    if scope == "agent" and not feedback.agent_id:
        raise ValueError(
            "feedback is not attributed to an agent, so an agent-scoped suppression has "
            "nothing to scope to; ask for scope='global' explicitly if that is intended"
        )

    hashed = None
    if exact:
        # The sample is the one this decision's run of *this* detector matched, highest
        # score first. Looking it up by trace alone, unordered, hashed whichever
        # detection the database returned first — possibly another detector's, or
        # another decision's on the same trace — so the "exact" suppression silenced
        # text nobody had labelled.
        finding = _labelled_detection(session, feedback)
        hashed = sample_hash(finding.sample) if finding and finding.sample else None
        if hashed is None:
            # Falling back to a class-wide suppression when an exact one was asked for
            # would be a wider exception than anyone approved.
            raise ValueError(
                "no matched sample is recorded for this decision's detector, so an "
                "exact-match suppression cannot be built"
            )

    suppression = Suppression(
        feedback_id=feedback.id,
        agent_id=feedback.agent_id if scope == "agent" else None,
        detector_key=feedback.detector_key,
        entity_type=feedback.entity_type,
        sample_hash=hashed,
        reason=reason or feedback.note,
        created_by=actor or feedback.actor,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=ttl_days),
    )
    session.add(suppression)
    feedback.status = "applied"
    session.flush()

    # Silencing a detector is the one operator action that can hide every other
    # action, so it goes into the same chain as the decisions it will stop producing.
    record(
        session,
        "operator.guardrail.suppressed",
        actor=actor or feedback.actor or "unknown",
        reason=reason or feedback.note or f"false positive reported on {feedback.detector_key}",
        subject_type="detector",
        subject_id=feedback.detector_key,
        after={
            "scope": scope,
            "agent_id": suppression.agent_id,
            "entity_type": feedback.entity_type,
            "exact_sample": bool(hashed),
            "expires_at": suppression.expires_at.isoformat(),
        },
    )
    return suppression


def _labelled_detection(session: Session, feedback: GuardrailFeedback) -> DetectionFinding | None:
    """The detection a label is about: this decision, this detector, this entity."""
    decision = session.get(Decision, feedback.decision_id) if feedback.decision_id else None
    if decision is None or not decision.detector_run_ids:
        return None
    run_ids = list(
        session.scalars(
            select(DetectorRun.id).where(
                DetectorRun.id.in_(list(decision.detector_run_ids)),
                DetectorRun.detector_key == feedback.detector_key,
            )
        )
    )
    if not run_ids:
        return None
    stmt = select(DetectionFinding).where(DetectionFinding.detector_run_id.in_(run_ids))
    if feedback.entity_type:
        stmt = stmt.where(DetectionFinding.entity_type == feedback.entity_type)
    return session.scalar(
        stmt.order_by(DetectionFinding.score.desc(), DetectionFinding.id).limit(1)
    )


def active_suppressions(session: Session, agent_id: str | None) -> list[Suppression]:
    rows = session.scalars(
        select(Suppression).where(
            Suppression.revoked_at.is_(None),
            (Suppression.agent_id == agent_id) | (Suppression.agent_id.is_(None)),
        )
    )
    return [row for row in rows if row.active]


def revoke_suppression(
    session: Session,
    suppression_id: str,
    *,
    actor: str | None = None,
    reason: str = "",
) -> None:
    """Restore a suppressed detector.

    Recorded as deliberately as the suppression was: the pair is what lets an
    investigation say which detector was unwatched, and for how long.
    """
    suppression = session.get(Suppression, suppression_id)
    if suppression is None:
        raise ValueError("unknown suppression")
    suppression.revoked_at = dt.datetime.now(dt.UTC)
    session.flush()
    record(
        session,
        "operator.guardrail.unsuppressed",
        actor=actor or suppression.created_by or "unknown",
        reason=reason or "suppression revoked",
        subject_type="detector",
        subject_id=suppression.detector_key,
        before={
            "suppressed_since": suppression.created_at.isoformat()
            if getattr(suppression, "created_at", None)
            else None
        },
    )


def _matches(suppression: Suppression, detection: Detection, surface: str) -> bool:
    if suppression.detector_key and suppression.entity_type:
        if detection.entity_type != suppression.entity_type:
            return False
    if suppression.surface and suppression.surface != surface:
        return False
    if suppression.sample_hash:
        return bool(detection.sample) and sample_hash(detection.sample) == suppression.sample_hash
    return True


def filter_suppressed(
    pipeline_result: Any,
    suppressions: list[Suppression],
    *,
    surface: str,
) -> list[dict[str, Any]]:
    """Remove suppressed detections in place and return what was removed.

    Returning the removals is the whole point. A suppression that disappears from the
    record is a hole in the control; one that is recorded on the decision is a
    documented, expiring exception an auditor can read.
    """
    if not suppressions:
        return []
    removed: list[dict[str, Any]] = []
    for detector_result in getattr(pipeline_result, "results", []) or []:
        applicable = [s for s in suppressions if s.detector_key == detector_result.detector_key]
        if not applicable:
            continue
        kept = []
        for detection in detector_result.detections:
            hit = next((s for s in applicable if _matches(s, detection, surface)), None)
            if hit is None:
                kept.append(detection)
                continue
            hit.hits = (hit.hits or 0) + 1
            removed.append(
                {
                    "detector": detector_result.detector_key,
                    "entity_type": detection.entity_type,
                    "suppression_id": hit.id,
                    "expires_at": hit.expires_at.isoformat() if hit.expires_at else None,
                    "reason": hit.reason,
                }
            )
        detector_result.detections = kept
        if not kept:
            detector_result.score = 0.0
    return removed


def suppression_health(session: Session) -> dict[str, Any]:
    """Which suppressions are load-bearing, which are dead weight, which expire soon."""
    now = dt.datetime.now(dt.UTC)
    rows = list(session.scalars(select(Suppression)))
    soon, unused, active, expired = [], [], 0, 0
    for row in rows:
        if not row.active:
            expired += 1
            continue
        active += 1
        if row.hits == 0:
            unused.append(row.id)
        if row.expires_at is not None:
            expires = row.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=dt.UTC)
            if expires - now < dt.timedelta(days=7):
                soon.append(row.id)
    return {
        "active": active,
        "expired_or_revoked": expired,
        "never_hit": unused,
        "expiring_within_7_days": soon,
    }


def agent_id_for(session: Session, slug: str | None) -> str | None:
    if not slug:
        return None
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    return agent.id if agent else None


# ---------------------------------------------------------------------------
# Reconstructing an explanation after the fact
# ---------------------------------------------------------------------------


def explain_recorded(
    decision: dict[str, Any],
    detector_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rebuild the "why" of a decision from what was stored, long after the request.

    `explain()` runs on the live request and its output goes back in the HTTP
    response. Nothing persists it, which was fine while the only reader was the
    caller holding that response — and is not fine for the person this product is
    most used by. A platform engineer meets a block in a log line hours later, with
    a decision id and no idea what it means; the dashboard could show them the rules
    that fired and the detectors that ran, and left them to work out for themselves
    which of five detections was the one that mattered and what to do about it.

    Rebuilt rather than stored, for two reasons. Storing it would duplicate every
    span and score that `DetectionFinding` already holds, on the hottest table in
    the schema. And the rule's own entity predicate is now recorded in
    `rules_fired`, so the reconstruction selects the decisive match by the same test
    the live path uses and cannot quietly disagree with it.

    What is genuinely lost and not faked: the masked excerpt, which needs the
    original content, and per-detector timings beyond what the run rows carry. The
    caller gets `None` for the excerpt rather than a plausible-looking blank.
    """
    from agentfox.core.vocab import EFFECT_RANK

    rules = list(decision.get("rules_fired") or [])
    # The *effective* verdict, which is what the live explanation describes and what
    # the reader is asking about: in observe mode the applied verdict is `allow` and
    # the interesting sentence is the one about what would have happened. The
    # decision row stores only the applied verdict, so recover the other the same way
    # the policy engine computed it — the strongest effect among the rules that fired.
    applied = decision.get("verdict") or "allow"
    target = applied
    for fired in rules:
        effect = str(fired.get("effect") or "")
        if EFFECT_RANK.get(effect, -1) > EFFECT_RANK.get(target, -1):
            target = effect
    rule = next((r for r in rules if r.get("effect") == target), rules[0] if rules else None)

    exact = {str(e).upper() for e in (rule or {}).get("entities", []) or []}
    prefixes = tuple(str(e).upper() for e in (rule or {}).get("entity_prefixes", []) or [])

    run_ids = set(decision.get("detector_run_ids") or [])
    matches: list[dict[str, Any]] = []
    for run in detector_runs:
        # When the decision names its runs, honour that; a trace with several
        # decisions must not attribute one decision's matches to another.
        if run_ids and run.get("id") not in run_ids:
            continue
        for finding in run.get("findings") or []:
            matches.append(
                {
                    "detector": run.get("detector"),
                    "entity_type": finding.get("entity_type"),
                    "span": [finding.get("start"), finding.get("end")],
                    "score": finding.get("score"),
                    "owasp_id": finding.get("owasp_id"),
                    "atlas_id": finding.get("atlas_id"),
                    "decisive": False,
                }
            )

    relevant = [m for m in matches if _names(exact, prefixes, str(m["entity_type"] or ""))]
    decisive = max(relevant or matches, key=lambda m: m.get("score") or 0.0, default=None)
    if decisive is not None:
        decisive["decisive"] = True

    entity_types = [str(m["entity_type"]) for m in matches if m["decisive"]] or [
        str(m["entity_type"]) for m in matches
    ]
    summary = ""
    if decisive is not None:
        start, end = decisive["span"]
        summary = (
            f"{target} on {decision.get('surface', 'input')}: {decisive['entity_type']} "
            f"matched at offset {start}–{end} with score {decisive.get('score') or 0:.2f}"
        )
        if rule:
            summary += f", which rule `{rule.get('rule_id')}` treats as {rule.get('effect')}"
    elif rule:
        # A tool, capability or taint rule fires on no detection at all. Saying so is
        # the explanation; an empty panel is not.
        summary = (
            f"{target} on {decision.get('surface', 'input')}: rule "
            f"`{rule.get('rule_id')}` fired on something other than a detector match"
        )

    return {
        "summary": summary,
        "rule": rule,
        "matches": matches,
        "remedy": _remedy_for(entity_types, decision.get("surface", "input"))
        if entity_types
        else "",
        "dispute": {
            "endpoint": "POST /api/guardrails/feedback",
            "payload": {
                "decision_id": decision.get("id"),
                "label": "false_positive",
                "detector_key": decisive.get("detector") if decisive else None,
                "entity_type": decisive.get("entity_type") if decisive else None,
                "note": "why this was wrong",
            },
        },
    }
