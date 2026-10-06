"""Agent risk register, EU AI Act classification, obligations and board view.

Evidences NOM-GOV-03, NOM-GOV-05 and NOM-GOV-06.

Classification is *proposed* from what the platform observes — the tools an agent can
reach, whether a human is in the loop, what data classes it touches — and then
confirmed by a human, because Art. 6 classification is a legal determination and not
something a heuristic gets to make. The value is that the human starts from evidence
instead of a blank form.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import (
    Agent,
    Capability,
    ControlStatus,
    Finding,
    Identity,
    LineageEdge,
    Obligation,
    RiskAssessment,
    Tool,
    utcnow,
)

EU_CLASSES = ("prohibited", "high", "limited", "minimal")

#: Annex III-flavoured domain cues. Deliberately conservative and advisory.
_HIGH_RISK_CUES = {
    "employment": [
        "hiring",
        "recruit",
        "candidate",
        "cv",
        "resume",
        "performance review",
        "promotion",
        "termination",
    ],
    "credit": ["credit", "loan", "underwrit", "lending", "creditworthiness", "mortgage"],
    "essential_services": ["benefit", "welfare", "insurance", "eligibility", "housing"],
    "education": ["exam", "grading", "admission", "student assessment"],
    "law_enforcement": ["criminal", "policing", "suspect", "recidivism"],
    "migration": ["visa", "asylum", "immigration", "border"],
    "biometric": ["biometric", "facial recognition", "emotion recognition"],
    "critical_infrastructure": ["safety component", "traffic", "water supply", "power grid"],
    # Bare "triage" was too generic — it substring-matches "support-triage" and any
    # other customer-service/IT-ticket agent whose purpose or slug just says
    # "triages tickets", producing a false Annex III "medical" classification with
    # nothing medical about the agent. Scoped to phrases that only occur in a
    # clinical context.
    "medical": [
        "diagnos",
        "clinical triage",
        "patient triage",
        "triage nurse",
        "clinical",
        "patient care",
        "medical device",
    ],
}

_PROHIBITED_CUES = [
    "social scoring",
    "subliminal manipulation",
    "exploit vulnerabilit",
    "real-time remote biometric identification",
    "emotion recognition in the workplace",
    "predictive policing based on profiling",
]


def classify(session: Session, agent: Agent) -> dict[str, Any]:
    """Propose an EU AI Act risk class from observed and declared signals."""
    haystack = " ".join(
        [agent.purpose or "", agent.description or "", agent.name or "", agent.slug]
    ).lower()

    signals: list[str] = []
    proposed = "minimal"

    for cue in _PROHIBITED_CUES:
        if cue in haystack:
            signals.append(f"purpose text matches a prohibited-practice cue: '{cue}'")
            proposed = "prohibited"

    if proposed != "prohibited":
        for domain, cues in _HIGH_RISK_CUES.items():
            if any(cue in haystack for cue in cues):
                signals.append(f"purpose text suggests an Annex III domain: {domain}")
                proposed = "high"
                break

    # Capability signals: an agent that can take irreversible actions without a human
    # gate is materially riskier regardless of its stated domain.
    identities = list(session.scalars(select(Identity).where(Identity.agent_id == agent.id)))
    capabilities: list[Capability] = []
    for identity in identities:
        capabilities.extend(
            session.scalars(select(Capability).where(Capability.identity_id == identity.id))
        )

    tool_keys = {
        e.dst_id
        for e in session.scalars(
            select(LineageEdge).where(
                LineageEdge.src_id == agent.slug, LineageEdge.relation == "calls_tool"
            )
        )
    } | set(agent.declared_tools or [])

    irreversible = [
        t.key
        for t in session.scalars(select(Tool).where(Tool.key.in_(tool_keys or {"__none__"})))
        if t.impact in ("high_impact", "irreversible")
    ]
    if irreversible:
        signals.append(f"can invoke high-impact or irreversible tools: {sorted(irreversible)}")
        if proposed == "minimal":
            proposed = "limited"

    gated = [c.tool_key for c in capabilities if c.requires_approval]
    if irreversible and not gated:
        signals.append("no human-approval gate on any high-impact capability (Art. 14 concern)")
        if proposed in ("minimal", "limited"):
            proposed = "high"

    sensitive = [
        c
        for c in (agent.data_classes or [])
        if c.lower() in ("pii", "phi", "pci", "special_category", "biometric", "financial")
    ]
    if sensitive:
        signals.append(f"processes sensitive data classes: {sensitive}")
        if proposed == "minimal":
            proposed = "limited"

    if any(x in haystack for x in ("chat", "assistant", "customer", "support", "conversation")):
        signals.append("interacts directly with humans — Art. 50 transparency applies")
        if proposed == "minimal":
            proposed = "limited"

    return {
        "agent": agent.slug,
        "proposed_class": proposed,
        "current_class": agent.risk_tier,
        "signals": signals,
        "irreversible_tools": sorted(irreversible),
        "approval_gated_tools": sorted(gated),
        "requires_human_confirmation": True,
        "caveat": (
            "This is a proposed classification derived from observed capability and "
            "declared purpose. EU AI Act Art. 6 classification is a legal "
            "determination and must be confirmed by a qualified person."
        ),
    }


def assess(
    session: Session,
    agent: Agent,
    *,
    assessor: str,
    eu_ai_act_class: str | None = None,
    inherent_risk: str = "medium",
    mitigations: list[dict[str, Any]] | None = None,
    residual_risk: str = "low",
    answers: dict[str, Any] | None = None,
    review_months: int = 12,
    signed_off_by: str | None = None,
) -> RiskAssessment:
    proposal = classify(session, agent)
    assessment = RiskAssessment(
        agent_id=agent.id,
        eu_ai_act_class=eu_ai_act_class or proposal["proposed_class"],
        inherent_risk=inherent_risk,
        residual_risk=residual_risk,
        mitigations_json=mitigations or _default_mitigations(session, agent),
        answers_json={**(answers or {}), "classification_signals": proposal["signals"]},
        assessor=assessor,
        next_review_at=utcnow() + dt.timedelta(days=30 * review_months),
        signed_off_by=signed_off_by,
    )
    session.add(assessment)
    agent.risk_tier = assessment.eu_ai_act_class
    session.flush()
    return assessment


def _default_mitigations(session: Session, agent: Agent) -> list[dict[str, Any]]:
    """Pre-fill the mitigation list from controls that are actually operating.

    The point of a computed control status is that the risk register can cite
    evidence instead of intent.
    """
    statuses = {
        s.control_key: s
        for s in session.scalars(select(ControlStatus).order_by(ControlStatus.computed_at))
    }
    relevant = [
        ("NOM-RTG-01", "Inline prompt-injection detection and blocking"),
        ("NOM-RTG-02", "PII detection and redaction in both directions"),
        ("NOM-RTG-04", "Intent-based tool containment with argument provenance"),
        ("NOM-IAM-02", "Tool-scoped least privilege, default deny"),
        ("NOM-IAM-03", "Human approval on high-impact actions"),
        ("NOM-AUD-01", "Full execution-path recording"),
        ("NOM-AUD-02", "Tamper-evident audit log"),
        ("NOM-EVL-01", "Pre-release evaluation with regression gating"),
        ("NOM-EVL-03", "Silent-failure detection"),
    ]
    return [
        {
            "control": key,
            "description": description,
            "status": statuses[key].status if key in statuses else "not_implemented",
            "evidence": statuses[key].rationale if key in statuses else "no status computed",
        }
        for key, description in relevant
    ]


def register(session: Session) -> list[dict[str, Any]]:
    """The risk register: every agent, its class, its latest assessment."""
    latest: dict[str, RiskAssessment] = {}
    for assessment in session.scalars(select(RiskAssessment).order_by(RiskAssessment.assessed_at)):
        latest[assessment.agent_id] = assessment

    out: list[dict[str, Any]] = []
    for agent in session.scalars(select(Agent).where(Agent.status != "retired")):
        assessment = latest.get(agent.id)
        overdue = bool(
            assessment
            and assessment.next_review_at
            and _aware(assessment.next_review_at) < utcnow()
        )
        out.append(
            {
                "agent": agent.slug,
                "name": agent.name,
                "owner": agent.owner_email,
                "environment": agent.environment,
                "registered": agent.registered,
                "risk_tier": agent.risk_tier,
                "assessed": assessment is not None,
                "eu_ai_act_class": assessment.eu_ai_act_class if assessment else None,
                "inherent_risk": assessment.inherent_risk if assessment else None,
                "residual_risk": assessment.residual_risk if assessment else None,
                "assessor": assessment.assessor if assessment else None,
                "assessed_at": _iso(assessment.assessed_at) if assessment else None,
                "next_review_at": _iso(assessment.next_review_at) if assessment else None,
                "review_overdue": overdue,
                "signed_off": bool(assessment and assessment.signed_off_by),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Obligation calendar
# ---------------------------------------------------------------------------


def obligation_calendar(session: Session) -> list[dict[str, Any]]:
    """Obligations with the agents actually in scope for each."""
    agents = list(session.scalars(select(Agent).where(Agent.status != "retired")))
    now = utcnow()
    out: list[dict[str, Any]] = []

    for obligation in session.scalars(select(Obligation).order_by(Obligation.effective_date)):
        applies = obligation.applies_when_json or {}
        in_scope: list[str] = []
        for agent in agents:
            tiers = applies.get("risk_tier")
            if tiers and agent.risk_tier not in tiers:
                continue
            if applies.get("interacts_with_humans") and not _human_facing(agent):
                continue
            in_scope.append(agent.slug)

        effective = _aware(obligation.effective_date)
        days = (effective - now).days
        out.append(
            {
                "framework": obligation.framework,
                "reference": obligation.reference,
                "title": obligation.title,
                "description": obligation.description,
                "effective_date": _iso(obligation.effective_date),
                "days_until": days,
                "status": "live" if days <= 0 else obligation.status,
                "agents_in_scope": in_scope,
                "agents_in_scope_count": len(in_scope),
                # The demand pump: align delivery to land ~12 months ahead.
                "target_readiness": _iso(effective - dt.timedelta(days=365)) if days > 0 else None,
            }
        )
    return out


def _human_facing(agent: Agent) -> bool:
    haystack = f"{agent.purpose} {agent.description} {agent.name} {agent.slug}".lower()
    return any(
        cue in haystack
        for cue in ("chat", "assistant", "customer", "support", "conversation", "agent")
    )


# ---------------------------------------------------------------------------
# Board view
# ---------------------------------------------------------------------------


def board_view(session: Session) -> dict[str, Any]:
    from agentfox.capabilities.compliance.status import ensure_compliance_computed, posture
    from agentfox.platform.registry.service import inventory

    # Computed here rather than left to a separate `compliance compute`: without
    # it a fresh deployment's board read "0% of 43 controls".
    ensure_compliance_computed(session)

    agents = list(session.scalars(select(Agent).where(Agent.status != "retired")))
    findings = list(session.scalars(select(Finding).where(Finding.status == "open")))

    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        by_type[finding.type] = by_type.get(finding.type, 0) + 1

    by_class: dict[str, int] = {}
    for agent in agents:
        by_class[agent.risk_tier] = by_class.get(agent.risk_tier, 0) + 1

    frameworks = ["eu-ai-act", "nist-ai-rmf", "iso-42001", "soc2"]
    calendar = obligation_calendar(session)

    return {
        "generated_at": _iso(utcnow()),
        "inventory": inventory(session),
        "seed_agents": sum(1 for a in agents if a.is_seed),
        "agents_by_risk_class": by_class,
        "high_risk_agents": [a.slug for a in agents if a.risk_tier in ("high", "prohibited")],
        "unassessed_agents": [
            a.slug
            for a in agents
            if not session.scalar(select(RiskAssessment).where(RiskAssessment.agent_id == a.id))
        ],
        "open_findings": {
            "total": len(findings),
            "by_severity": by_severity,
            "by_type": by_type,
            "critical": [
                {"id": f.id, "title": f.title, "subject": f.subject_id}
                for f in findings
                if f.severity == "critical"
            ][:10],
        },
        "control_posture": {fw: posture(session, fw) for fw in frameworks},
        "overall_posture": posture(session),
        "upcoming_obligations": [
            o for o in calendar if o["days_until"] is not None and 0 < o["days_until"] <= 730
        ],
        "live_obligations": [o for o in calendar if o["status"] == "live"],
        "caveat": (
            "Control statuses are computed from telemetry over the stated window. "
            "Framework mappings are DRAFT and have not been reviewed by compliance "
            "counsel — see the coverage and gap declarations per framework."
        ),
    }


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def _iso(value: dt.datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None
