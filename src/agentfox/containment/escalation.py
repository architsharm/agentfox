"""Escalation governance. The largest single failure family, at 31.1%.

Everyone ships the *mechanism* to escalate. LangGraph has `interrupt()`, Temporal has
durable HITL workflows, Zendesk and ServiceNow have handoff queues, and the
practitioner evidence confirms teams build these routinely — two of eleven engineers
had shipped HITL escalation pipelines by hand.

**Nobody detects the counterfactual: it met an escalation condition and did not
escalate.** That is the only novel claim here, and this module is built around it.

The asymmetry is why. Escalation is the one control whose failure is *invisible from
inside the system*: a blocked action leaves a decision, a crashed agent leaves a
trace, but an agent that should have handed off and instead kept going leaves a
perfectly ordinary-looking conversation. The user gives up and churns, and nothing in
the telemetry says anything went wrong. Detection therefore has to be a deliberate
second pass over completed conversations, replaying the declared policy against what
was recorded — not a runtime check, because at runtime there is nothing to see.

Six conditions are supported, drawn from the catalogued modes rather than invented:
repeated failure, low confidence, user frustration or distress, regulated topic,
repeated abstention, and turn depth. A seventh — explicit user request — is treated
as unconditional, because "let me talk to a human" is not a signal to be weighed.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import (
    Agent,
    ConversationTurn,
    EscalationPolicy,
    Handoff,
    utcnow,
)
from agentfox.prove.findings import raise_finding

log = logging.getLogger(__name__)

#: Default conditions. Deliberately conservative — an escalation policy that fires on
#: everything trains humans to ignore the queue, which is worse than not having one.
DEFAULT_CONDITIONS: dict[str, Any] = {
    "explicit_request": True,
    "repeated_failure": 2,
    "repeated_abstention": 2,
    "turn_depth": 8,
    "sentiment_below": -0.6,
    "regulated_topics": ["legal", "medical", "financial_advice", "complaint", "discrimination"],
    "confidence_below": 0.35,
}

# --- Signal lexicons -------------------------------------------------------
# Lexical rather than model-based, and honest about it: these are weak signals feeding
# a policy, not classifiers. The counter-metric (false escalation) is tracked, and the
# whole pillar ships observe-first for exactly this reason.

_EXPLICIT_REQUEST = [
    r"\b(?:speak|talk|connect|transfer)\s+(?:me\s+)?(?:to|with)\s+(?:an?\s+)?"
    r"(?:human|person|agent|representative|someone|manager|supervisor)\b",
    r"\breal\s+(?:person|human)\b",
    r"\bescalate\b",
    r"\b(?:get|give)\s+me\s+(?:an?\s+)?(?:human|manager|supervisor)\b",
    r"\bstop\s+(?:the\s+)?(?:bot|chatbot|ai)\b",
    # "I want a manager" is the same request as "connect me to a manager"; a pattern
    # set that only recognises the polite phrasings misses the frustrated ones, which
    # are exactly the conversations that needed escalating.
    r"\bi (?:want|need|would like)\s+(?:to\s+(?:speak|talk)\s+(?:to|with)\s+)?"
    r"(?:an?\s+)?(?:human|person|agent|representative|manager|supervisor)\b",
]

_FRUSTRATION = [
    (r"\b(?:this is )?(?:ridiculous|unacceptable|outrageous|appalling)\b", -0.9),
    (r"\b(?:furious|livid|disgusted|fed up)\b", -0.9),
    (r"\b(?:useless|worthless|garbage|rubbish|nonsense)\b", -0.7),
    (r"\bi(?:'| a)?m (?:so )?(?:angry|frustrated|upset|annoyed)\b", -0.7),
    (r"\b(?:still|again) (?:not|doesn'?t|isn'?t) work", -0.6),
    (
        r"\b(?:third|fourth|fifth|\d+(?:st|nd|rd|th)) time (?:i|we)(?:'ve| have)? "
        r"(?:asked|tried|contacted)\b",
        -0.8,
    ),
    (r"\b(?:you|this) (?:are|is) not (?:listening|helping|understanding)\b", -0.7),
    (r"\bwaste of (?:my )?time\b", -0.7),
    (r"!{3,}", -0.4),
]

#: Distress and legal exposure are escalation conditions in their own right, not
#: sentiment. Weighing "I want to hurt myself" against a satisfaction score is wrong.
_URGENT = [
    (r"\b(?:suicide|suicidal|kill myself|hurt myself|self.harm|end my life)\b", "self_harm"),
    (r"\b(?:emergency|urgent|life.threatening|dying)\b", "urgency"),
    (r"\b(?:lawyer|attorney|solicitor|legal action|sue|lawsuit|litigation)\b", "legal_threat"),
    (r"\b(?:regulator|ombudsman|fca|sec|ftc|data protection authority|ico)\b", "regulatory"),
    (r"\b(?:discriminat|racist|sexist|harass)\w*\b", "discrimination"),
]

_TOPIC_MARKERS = {
    "legal": [r"\b(?:contract|liability|terms and conditions|breach|indemnit)\w*\b", r"\blegal\b"],
    "medical": [r"\b(?:diagnos|symptom|prescri|dosage|medication|treatment)\w*\b"],
    "financial_advice": [r"\b(?:invest|portfolio|which fund|should i buy|financial advice)\w*\b"],
    "complaint": [r"\b(?:complain|complaint|escalat|formal grievance)\w*\b"],
    "discrimination": [r"\b(?:discriminat|racist|sexist|ageis|disabilit)\w*\b"],
}

#: A resolution claim the agent makes about itself.
_RESOLUTION_CLAIMS = [
    r"\b(?:i(?:'ve| have)?\s+)?(?:resolved|fixed|sorted|completed|taken care of)\b",
    r"\bis (?:now )?(?:resolved|fixed|complete|sorted)\b",
    r"\banything else (?:i can help|you need)\b",
    r"\bglad (?:i could|to have) help",
    r"\bmarking this (?:as )?(?:resolved|closed)\b",
]

#: An agent declining is not the same as an agent escalating. Repeated
#: abstention with no hand-off is the shape where the user gets nothing and leaves.
_ABSTENTION = [
    r"\bi (?:don'?t|do not) have (?:that|access|the)\b[^.!?]{0,40}"
    r"\b(?:information|data|details|record)\b",
    r"\bi(?:'m| am) (?:not able|unable) to (?:help|assist|answer)\b",
    r"\bthat(?:'s| is) (?:outside|beyond) (?:my|the) (?:scope|remit|knowledge)\b",
    r"\bi can'?t (?:help|assist) with (?:that|this)\b",
    r"\bi (?:cannot|can'?t) (?:access|see|retrieve)\b",
]

_EXPLICIT_RE = [re.compile(p, re.I) for p in _EXPLICIT_REQUEST]
_FRUSTRATION_RE = [(re.compile(p, re.I), w) for p, w in _FRUSTRATION]
_URGENT_RE = [(re.compile(p, re.I), label) for p, label in _URGENT]
_TOPIC_RE = {k: [re.compile(p, re.I) for p in v] for k, v in _TOPIC_MARKERS.items()}
_RESOLUTION_RE = [re.compile(p, re.I) for p in _RESOLUTION_CLAIMS]
_ABSTENTION_RE = [re.compile(p, re.I) for p in _ABSTENTION]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def sentiment_signal(text: str) -> dict[str, Any]:
    """Frustration, distress and legal exposure in one pass.

    Distress and legal threats are returned as *flags* rather than folded into the
    score, because they are escalation conditions in their own right. Averaging "I'm
    going to call my lawyer" into a satisfaction number is how a system misses the one
    message that mattered.
    """
    if not text:
        return {"score": 0.0, "flags": [], "matched": []}
    score = 0.0
    matched: list[str] = []
    for pattern, weight in _FRUSTRATION_RE:
        if pattern.search(text):
            score += weight
            matched.append(pattern.pattern)
    flags = sorted({label for pattern, label in _URGENT_RE if pattern.search(text)})
    return {"score": max(-1.0, score), "flags": flags, "matched": matched}


def explicit_handoff_request(text: str) -> bool:
    """ "Let me talk to a human" is not a signal to be weighed against others."""
    return any(p.search(text or "") for p in _EXPLICIT_RE)


def topic_signal(text: str) -> list[str]:
    return sorted(
        topic
        for topic, patterns in _TOPIC_RE.items()
        if any(p.search(text or "") for p in patterns)
    )


def is_abstention(text: str) -> bool:
    return any(p.search(text or "") for p in _ABSTENTION_RE)


def claims_resolution(text: str) -> bool:
    return any(p.search(text or "") for p in _RESOLUTION_RE)


def turn_signals(user_text: str, agent_text: str) -> dict[str, Any]:
    """Everything the escalation conditions are written against, extracted once."""
    sentiment = sentiment_signal(user_text)
    return {
        "sentiment": sentiment["score"],
        "flags": sentiment["flags"],
        "explicit_request": explicit_handoff_request(user_text),
        "topics": topic_signal(f"{user_text} {agent_text}"),
        "abstained": is_abstention(agent_text),
        "claims_resolution": claims_resolution(agent_text),
    }


# ---------------------------------------------------------------------------
# Turn capture
# ---------------------------------------------------------------------------


def record_turn(
    session: Session,
    *,
    session_id: str,
    agent_id: str | None = None,
    trace_id: str | None = None,
    user_text: str = "",
    agent_text: str = "",
    escalated: bool = False,
    failed: bool = False,
    confidence: float | None = None,
    act: bool = True,
) -> ConversationTurn:
    """Capture one turn with its signals.

    With ``act`` (the default) a conversation under an enforcing escalation policy is
    handed off as soon as it qualifies (see `handoff_if_due`).

    Signals are extracted at capture time rather than at detection time so that
    missed-escalation detection reads a stable record: re-deriving them later against
    a changed lexicon would make yesterday's conversations answer differently.
    """
    last = session.scalars(
        select(ConversationTurn)
        .where(ConversationTurn.session_id == session_id)
        .order_by(ConversationTurn.turn_index.desc())
    ).first()
    signals = turn_signals(user_text, agent_text)
    signals["failed"] = failed
    if confidence is not None:
        signals["confidence"] = confidence
    if last is not None and user_text:
        signals["repeats_previous"] = _similar(last.user_text, user_text)

    turn = ConversationTurn(
        session_id=session_id,
        agent_id=agent_id,
        trace_id=trace_id,
        turn_index=(last.turn_index + 1) if last else 0,
        user_text=user_text,
        agent_text=agent_text,
        signals_json=signals,
        resolved_claimed=signals["claims_resolution"],
        escalated=escalated,
    )
    session.add(turn)
    session.flush()
    if act:
        handoff_if_due(session, session_id=session_id, agent_id=agent_id, trace_id=trace_id)
    return turn


def handoff_if_due(
    session: Session,
    *,
    session_id: str,
    agent_id: str | None,
    trace_id: str | None = None,
) -> Handoff | None:
    """In enforce mode, hand the conversation to a person the moment it qualifies.

    This is what the policy's ``mode`` means at runtime. In ``observe`` (the default)
    nothing is queued live: the scheduled ``escalation.scan`` job records the missed
    escalation as a finding instead. In ``enforce`` the conversation is handed off on
    the turn that first meets a condition, rather than hours later by a scan. One
    hand-off per conversation; an agent that escalated on its own needs none.
    """
    policy = get_policy(session, agent_id)
    if policy.mode != "enforce" or policy.enabled is False:
        return None
    if session.scalar(select(Handoff.id).where(Handoff.session_id == session_id)) is not None:
        return None
    turns = list(
        session.scalars(select(ConversationTurn).where(ConversationTurn.session_id == session_id))
    )
    assessment = assess(turns, policy)
    if not assessment.missed:
        return None
    return raise_handoff(
        session,
        agent_id=agent_id,
        session_id=session_id,
        trace_id=trace_id or next((t.trace_id for t in turns if t.trace_id), None),
        triggers=assessment.triggers,
        context=build_context(turns, "escalation conditions met (enforce mode)"),
        policy=policy,
    )


def _similar(a: str, b: str, threshold: float = 0.75) -> bool:
    """A user restating the same question is the clearest failure signal there is."""
    import difflib

    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a.lower()[:400], b.lower()[:400]).ratio() >= threshold


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def get_policy(session: Session, agent_id: str | None) -> EscalationPolicy:
    """The agent's policy, falling back to the global default, then to code defaults."""
    policy = None
    if agent_id:
        policy = session.scalar(
            select(EscalationPolicy).where(EscalationPolicy.agent_id == agent_id)
        )
    if policy is None:
        policy = session.scalar(select(EscalationPolicy).where(EscalationPolicy.agent_id.is_(None)))
    if policy is None:
        # Transient: never added to the session, so column defaults do not apply and
        # every field the callers read has to be set explicitly here.
        policy = EscalationPolicy(
            agent_id=None,
            conditions_json=dict(DEFAULT_CONDITIONS),
            owner_role="support",
            sla_minutes=60,
            enabled=True,
            mode="observe",
        )
    return policy


def set_policy(
    session: Session,
    *,
    agent_id: str | None,
    conditions: dict[str, Any] | None = None,
    owner_role: str = "support",
    sla_minutes: int = 60,
    mode: str = "observe",
) -> EscalationPolicy:
    policy = session.scalar(select(EscalationPolicy).where(EscalationPolicy.agent_id == agent_id))
    if policy is None:
        policy = EscalationPolicy(agent_id=agent_id)
        session.add(policy)
    policy.conditions_json = {**DEFAULT_CONDITIONS, **(conditions or {})}
    policy.owner_role = owner_role
    policy.sla_minutes = sla_minutes
    policy.mode = mode
    session.flush()
    return policy


@dataclass
class Trigger:
    condition: str
    detail: str
    turn_index: int
    severity: str = "medium"

    def to_json(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "detail": self.detail,
            "turn_index": self.turn_index,
            "severity": self.severity,
        }


@dataclass
class EscalationAssessment:
    should_escalate: bool
    triggers: list[Trigger] = field(default_factory=list)
    escalated: bool = False
    turns: int = 0

    @property
    def missed(self) -> bool:
        """The counterfactual: it qualified, and it did not happen."""
        return self.should_escalate and not self.escalated

    def to_json(self) -> dict[str, Any]:
        return {
            "should_escalate": self.should_escalate,
            "escalated": self.escalated,
            "missed": self.missed,
            "turns": self.turns,
            "triggers": [t.to_json() for t in self.triggers],
        }


def assess(
    turns: list[ConversationTurn], policy: EscalationPolicy | None = None
) -> EscalationAssessment:
    """Replay the declared conditions over a conversation.

    Pure and side-effect free so the same function serves runtime checks, the
    post-hoc detector, and policy simulation. A detector that cannot be run against
    yesterday's traffic cannot be tuned before it is turned on.
    """
    conditions = (policy.conditions_json if policy else None) or DEFAULT_CONDITIONS
    triggers: list[Trigger] = []
    failures = abstentions = 0

    for turn in sorted(turns, key=lambda t: t.turn_index):
        signals = turn.signals_json or {}

        if conditions.get("explicit_request") and signals.get("explicit_request"):
            triggers.append(
                Trigger("explicit_request", "the user asked for a human", turn.turn_index, "high")
            )

        for flag in signals.get("flags") or []:
            triggers.append(
                Trigger(
                    f"flag:{flag}",
                    f"'{flag}' detected — an escalation condition in its own right",
                    turn.turn_index,
                    "critical" if flag == "self_harm" else "high",
                )
            )

        floor = conditions.get("sentiment_below")
        if floor is not None and signals.get("sentiment", 0.0) <= floor:
            triggers.append(
                Trigger(
                    "sentiment",
                    f"sentiment {signals.get('sentiment'):.2f} at or below {floor}",
                    turn.turn_index,
                    "high",
                )
            )

        regulated = set(conditions.get("regulated_topics") or [])
        hit = regulated.intersection(signals.get("topics") or [])
        if hit:
            triggers.append(
                Trigger(
                    "regulated_topic",
                    f"regulated topic(s): {', '.join(sorted(hit))}",
                    turn.turn_index,
                    "high",
                )
            )

        threshold = conditions.get("confidence_below")
        if (
            threshold is not None
            and signals.get("confidence") is not None
            and signals["confidence"] <= threshold
        ):
            triggers.append(
                Trigger(
                    "low_confidence",
                    f"confidence {signals['confidence']:.2f} at or below {threshold}",
                    turn.turn_index,
                )
            )

        if signals.get("failed") or signals.get("repeats_previous"):
            failures += 1
            limit = conditions.get("repeated_failure")
            if limit is not None and failures == limit:
                triggers.append(
                    Trigger(
                        "repeated_failure",
                        f"{failures} failed or repeated turns — the user is restating the "
                        "same request",
                        turn.turn_index,
                        "high",
                    )
                )

        if signals.get("abstained"):
            abstentions += 1
            limit = conditions.get("repeated_abstention")
            if limit is not None and abstentions == limit:
                triggers.append(
                    Trigger(
                        "repeated_abstention",
                        f"{abstentions} consecutive declines with no hand-off — declining is "
                        "not the same as escalating",
                        turn.turn_index,
                        "high",
                    )
                )

    depth_limit = conditions.get("turn_depth")
    if depth_limit is not None and len(turns) >= depth_limit:
        triggers.append(
            Trigger(
                "turn_depth",
                f"{len(turns)} turns without resolution (limit {depth_limit})",
                len(turns) - 1,
            )
        )

    return EscalationAssessment(
        should_escalate=bool(triggers),
        triggers=triggers,
        escalated=any(t.escalated for t in turns),
        turns=len(turns),
    )


def turn_depth_risk(turns: list[ConversationTurn], policy: EscalationPolicy | None = None) -> dict:
    """Quality degradation past a depth the agent was never evaluated at."""
    conditions = (policy.conditions_json if policy else None) or DEFAULT_CONDITIONS
    limit = int(conditions.get("turn_depth", 8))
    depth = len(turns)
    late = [t for t in turns if t.turn_index >= limit // 2]
    late_abstentions = sum(1 for t in late if (t.signals_json or {}).get("abstained"))
    return {
        "depth": depth,
        "limit": limit,
        "exceeded": depth >= limit,
        "late_abstention_rate": round(late_abstentions / len(late), 3) if late else 0.0,
        "degrading": bool(late) and late_abstentions / len(late) > 0.5,
    }


# ---------------------------------------------------------------------------
# Hand-off
# ---------------------------------------------------------------------------

#: What a human needs to take over without re-interviewing the user. Missing any of
#: these is an incomplete hand-off — the escalation happened and was still a failure.
REQUIRED_CONTEXT = (
    "user_request",
    "conversation_summary",
    "attempted_actions",
    "blocking_reason",
    "customer_reference",
)


def handoff_completeness(context: dict[str, Any]) -> dict[str, Any]:
    """Score the context package a human is about to receive."""
    present = [k for k in REQUIRED_CONTEXT if str((context or {}).get(k) or "").strip()]
    missing = [k for k in REQUIRED_CONTEXT if k not in present]
    return {
        "score": round(len(present) / len(REQUIRED_CONTEXT), 3),
        "present": present,
        "missing": missing,
        "complete": not missing,
    }


def build_context(turns: list[ConversationTurn], blocking_reason: str = "") -> dict[str, Any]:
    """Assemble the hand-off package from what was actually recorded."""
    ordered = sorted(turns, key=lambda t: t.turn_index)
    if not ordered:
        return {}
    attempted = [
        f"turn {t.turn_index}: "
        + ("declined" if (t.signals_json or {}).get("abstained") else "answered")
        for t in ordered
    ]
    return {
        "user_request": ordered[0].user_text,
        "conversation_summary": " → ".join(
            f"[{t.turn_index}] {t.user_text[:80]}" for t in ordered[-4:]
        ),
        "attempted_actions": attempted,
        "blocking_reason": blocking_reason or "escalation conditions met",
        "customer_reference": ordered[0].session_id,
        "turns": len(ordered),
    }


def raise_handoff(
    session: Session,
    *,
    agent_id: str | None,
    session_id: str,
    trace_id: str | None,
    triggers: list[Trigger],
    context: dict[str, Any],
    policy: EscalationPolicy | None = None,
    retroactive: bool = False,
) -> Handoff:
    policy = policy or get_policy(session, agent_id)
    completeness = handoff_completeness(context)
    handoff = Handoff(
        agent_id=agent_id,
        trace_id=trace_id,
        session_id=session_id,
        reason="; ".join(t.detail for t in triggers) or "escalation conditions met",
        triggers_json=[t.to_json() for t in triggers],
        context_json=context,
        completeness=completeness["score"],
        owner_role=policy.owner_role,
        due_at=utcnow() + dt.timedelta(minutes=policy.sla_minutes),
        detected_retroactively=retroactive,
    )
    session.add(handoff)

    # An incomplete hand-off is its own failure: the hand-off happened *and* the human
    # cannot act on it.
    if not completeness["complete"]:
        raise_finding(
            session,
            type="incomplete_handoff",
            severity="medium",
            title=f"Hand-off missing context: {', '.join(completeness['missing'])}",
            subject_type="agent",
            subject_id=agent_id,
            evidence={"session_id": session_id, **completeness},
            control_keys=["NOM-RTG-10"],
            fingerprint_parts=(session_id,),
        )
    session.flush()
    return handoff


def breached_handoffs(session: Session) -> list[Handoff]:
    """Hand-offs past their SLA that nobody has picked up.

    An escalation raised into a queue nobody watches is the same outcome as no
    escalation, and it is worse in one respect: the system believes it did its job.
    """
    now = utcnow()
    breached: list[Handoff] = []
    for handoff in session.scalars(select(Handoff).where(Handoff.status == "pending")):
        due = handoff.due_at
        if due is None:
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=dt.UTC)
        if due >= now:
            continue
        handoff.status = "breached"
        breached.append(handoff)
        raise_finding(
            session,
            type="handoff_sla_breach",
            severity="high",
            title=f"Hand-off unacknowledged past its {handoff.owner_role} SLA",
            subject_type="agent",
            subject_id=handoff.agent_id,
            evidence={
                "handoff_id": handoff.id,
                "session_id": handoff.session_id,
                "due_at": due.isoformat(),
                "reason": handoff.reason,
            },
            control_keys=["NOM-RTG-10"],
            fingerprint_parts=(handoff.id,),
            once=True,
        )
    session.flush()
    return breached


# ---------------------------------------------------------------------------
# The control: missed escalation
# ---------------------------------------------------------------------------


def detect_missed_escalation(
    session: Session,
    *,
    since_hours: int = 24,
    agent_slug: str | None = None,
    raise_findings: bool = True,
    retroactive_handoffs: bool | None = True,
) -> dict[str, Any]:
    """**The 31% control.** Which conversations qualified for a hand-off and got none?

    Runs as a second pass rather than at runtime, because at runtime there is nothing
    to see: the failure is the *absence* of an event, and absence is only visible once
    the conversation is over.

    ``retroactive_handoffs`` decides whether acting (``raise_findings``) also queues a
    hand-off for each missed conversation: True always (an operator's explicit scan),
    False never, None per the conversation's escalation policy — only where its mode
    is ``enforce``. The scheduled ``escalation.scan`` job passes None, so an observing
    policy is recorded as findings and nothing is queued on its behalf.
    """
    since = utcnow() - dt.timedelta(hours=since_hours)
    stmt = select(ConversationTurn).where(ConversationTurn.created_at >= since)
    if agent_slug:
        agent = session.scalar(select(Agent).where(Agent.slug == agent_slug))
        if agent is None:
            return {"conversations": 0, "missed": [], "qualified": 0}
        stmt = stmt.where(ConversationTurn.agent_id == agent.id)

    sessions: dict[str, list[ConversationTurn]] = {}
    for turn in session.scalars(stmt):
        sessions.setdefault(turn.session_id, []).append(turn)

    missed: list[dict[str, Any]] = []
    qualified = 0
    for session_id, turns in sessions.items():
        agent_id = next((t.agent_id for t in turns if t.agent_id), None)
        assessment = assess(turns, get_policy(session, agent_id))
        if assessment.should_escalate:
            qualified += 1
        if not assessment.missed:
            continue
        if session.scalar(select(Handoff).where(Handoff.session_id == session_id)) is not None:
            continue

        record = {
            "session_id": session_id,
            "agent_id": agent_id,
            "turns": assessment.turns,
            "triggers": [t.to_json() for t in assessment.triggers],
            "first_qualifying_turn": min(t.turn_index for t in assessment.triggers),
        }
        missed.append(record)

        if raise_findings:
            policy = get_policy(session, agent_id)
            queue = (
                policy.mode == "enforce"
                if retroactive_handoffs is None
                else bool(retroactive_handoffs)
            )
            record["handed_off"] = queue
            severity = (
                "critical" if any(t.severity == "critical" for t in assessment.triggers) else "high"
            )
            raise_finding(
                session,
                type="missed_escalation",
                severity=severity,
                title=(
                    f"Conversation met {len(assessment.triggers)} escalation condition(s) "
                    f"from turn {record['first_qualifying_turn']} and never handed off"
                ),
                subject_type="agent",
                subject_id=agent_id,
                evidence=record,
                control_keys=["NOM-RTG-10"],
                fingerprint_parts=(session_id,),
                once=True,
            )
            # Retroactive hand-off: the point is that a real person is still waiting.
            # Recording the finding and leaving them waiting would be an audit artefact,
            # not a control — so it is queued whenever the scan is allowed to act.
            if queue:
                raise_handoff(
                    session,
                    agent_id=agent_id,
                    session_id=session_id,
                    trace_id=next((t.trace_id for t in turns if t.trace_id), None),
                    triggers=assessment.triggers,
                    context=build_context(
                        turns, "detected retroactively by missed-escalation scan"
                    ),
                    policy=policy,
                    retroactive=True,
                )

    session.flush()
    return {
        "window_hours": since_hours,
        "conversations": len(sessions),
        "qualified": qualified,
        "missed": missed,
        "missed_rate": round(len(missed) / qualified, 4) if qualified else 0.0,
    }


# ---------------------------------------------------------------------------
# Loop instead of escalate, false resolution
# ---------------------------------------------------------------------------


def _loop_without_handoff(session: Session, session_id: str) -> bool:
    """Breaking a loop is not the same as handing it off.

    The existing loop breaker stops the agent burning budget. It does nothing for the
    user, who is still on the other end with an unsolved problem.
    """
    turns = list(
        session.scalars(select(ConversationTurn).where(ConversationTurn.session_id == session_id))
    )
    if not turns:
        return False
    repeats = sum(1 for t in turns if (t.signals_json or {}).get("repeats_previous"))
    handed_off = session.scalar(select(Handoff).where(Handoff.session_id == session_id)) is not None
    return repeats >= 2 and not handed_off


def detect_false_resolution(
    session: Session,
    *,
    since_hours: int = 24,
    agent_id: str | None = None,
    raise_findings: bool = True,
) -> list[dict[str, Any]]:
    """The agent said it was resolved and the conversation says otherwise.

    Three signals, any of which contradicts a resolution claim: the user came back
    afterwards, the claim sat on top of an abstention, or the closing sentiment was
    negative. "Anything else I can help with?" after declining to help is the shape.
    """
    since = utcnow() - dt.timedelta(hours=since_hours)
    stmt = select(ConversationTurn).where(ConversationTurn.created_at >= since)
    if agent_id:
        stmt = stmt.where(ConversationTurn.agent_id == agent_id)
    sessions: dict[str, list[ConversationTurn]] = {}
    for turn in session.scalars(stmt):
        sessions.setdefault(turn.session_id, []).append(turn)

    out: list[dict[str, Any]] = []
    for session_id, turns in sessions.items():
        ordered = sorted(turns, key=lambda t: t.turn_index)
        for i, turn in enumerate(ordered):
            if not turn.resolved_claimed:
                continue
            signals = turn.signals_json or {}
            contradictions = []
            if i < len(ordered) - 1:
                contradictions.append("the user continued after the resolution claim")
            if signals.get("abstained"):
                contradictions.append("the same turn declined to answer")
            if signals.get("sentiment", 0.0) <= -0.5:
                contradictions.append("closing sentiment was negative")
            if not contradictions:
                continue

            record = {
                "session_id": session_id,
                "agent_id": turn.agent_id,
                "turn_index": turn.turn_index,
                "contradictions": contradictions,
            }
            out.append(record)
            if raise_findings:
                # One finding per contradicted claim. A re-scan over the same window
                # sees the same turn again; that is the same event, not a new one.
                raise_finding(
                    session,
                    type="false_resolution",
                    severity="high",
                    title="Agent claimed resolution the conversation contradicts",
                    subject_type="agent",
                    subject_id=turn.agent_id,
                    evidence=record,
                    control_keys=["NOM-RTG-10"],
                    fingerprint_parts=(session_id, turn.turn_index),
                    once=True,
                )
    session.flush()
    return out


def escalation_report(
    session: Session, *, since_hours: int = 24, agent_slug: str | None = None
) -> dict[str, Any]:
    """Everything an operator needs to answer "is escalation working?"."""
    agent_id = None
    if agent_slug:
        agent = session.scalar(select(Agent).where(Agent.slug == agent_slug))
        agent_id = agent.id if agent else agent_slug  # unknown slug -> matches nothing

    missed = detect_missed_escalation(
        session, since_hours=since_hours, agent_slug=agent_slug, raise_findings=False
    )
    false_res = detect_false_resolution(
        session, since_hours=since_hours, agent_id=agent_id, raise_findings=False
    )
    handoff_stmt = select(Handoff)
    turns_stmt = select(ConversationTurn)
    if agent_id:
        handoff_stmt = handoff_stmt.where(Handoff.agent_id == agent_id)
        turns_stmt = turns_stmt.where(ConversationTurn.agent_id == agent_id)
    breached = [h for h in session.scalars(handoff_stmt) if h.status == "breached"]
    handoffs = list(session.scalars(handoff_stmt))
    incomplete = [h for h in handoffs if h.completeness < 1.0]
    loops = [
        sid
        for sid in {t.session_id for t in session.scalars(turns_stmt)}
        if _loop_without_handoff(session, sid)
    ]
    return {
        "window_hours": since_hours,
        "conversations": missed["conversations"],
        "qualified_for_escalation": missed["qualified"],
        "missed_escalations": len(missed["missed"]),
        # The headline metric. Target: < 5% of qualifying conversations.
        "missed_rate": missed["missed_rate"],
        "handoffs": len(handoffs),
        "incomplete_handoffs": len(incomplete),
        "sla_breached": len(breached),
        "false_resolutions": len(false_res),
        "loops_without_handoff": loops,
    }


def run_scan(
    session: Session,
    *,
    since_hours: int = 24,
    agent_slug: str | None = None,
    retroactive_handoffs: bool | None = True,
) -> dict[str, Any]:
    """Run detection and act on it: findings, hand-offs, false resolutions, SLA breaches.

    The one acting path, shared by `POST /api/escalation/scan`, `agentfox report
    escalations --apply` (both ``retroactive_handoffs=True``: an operator asked) and the
    scheduled ``escalation.scan`` job (None: hand off only where the policy enforces).
    """
    agent_id = None
    if agent_slug:
        agent = session.scalar(select(Agent).where(Agent.slug == agent_slug))
        agent_id = agent.id if agent else agent_slug  # unknown slug -> matches nothing
    missed = detect_missed_escalation(
        session,
        since_hours=since_hours,
        agent_slug=agent_slug,
        raise_findings=True,
        retroactive_handoffs=retroactive_handoffs,
    )
    false_resolutions = detect_false_resolution(session, since_hours=since_hours, agent_id=agent_id)
    breached = breached_handoffs(session)
    return {
        **missed,
        "handed_off": sum(1 for m in missed["missed"] if m.get("handed_off")),
        "false_resolutions": len(false_resolutions),
        "sla_breached": [h.id for h in breached],
    }


def scheduled_scan(session: Session, *, since_hours: int = 24) -> dict[str, Any]:
    """The ``escalation.scan`` job: the second pass, run on a schedule.

    Without it, missed escalations, false resolutions and SLA breaches only surfaced
    when someone ran `agentfox report escalations --apply` by hand. Findings are raised
    for every agent; retroactive hand-offs only where the escalation policy enforces;
    overdue hand-offs are marked breached.
    """
    result = run_scan(session, since_hours=since_hours, retroactive_handoffs=None)
    result["missed"] = len(result["missed"])
    return result
