"""What can be done about an issue, from the issue, and the check that it was done.

An issue page that can only show evidence and be marked resolved leaves the fix to
the reader, somewhere else, by hand, and leaves the queue to trust their word that
it happened. This is the other half: for each finding type, the concrete actions the
platform itself can take (revoke a wildcard grant, register a shadow agent, grant the
tool an agent keeps being refused, declare a tool, record a false positive, add the
run to the regression tests), each one audited, and each followed by a re-check of the
condition the finding is about. When the condition has cleared the finding closes
itself, as an automated resolution, so "resolved" stays a fact and not a claim.

Two kinds of remedy:

* ``action`` — performed here by `apply_remedy`, under a permission family the
  gateway checks (`family`), recorded on the operator log as
  ``operator.finding.remedied`` with what was done.
* ``link`` — a place in the dashboard where the fix is made (a run to read, the
  checks screen, a rule's tuning tab). Offered only where no single action is right.

Catalogue, by finding type (actions first, links after):

=========================  ==================================================
over_privileged            replace ``*`` with the tools it uses · revoke ``*``
stale_identity             revoke its grants · retire the identity
orphaned_identity          retire the identity
shadow_agent               register · block
unowned_agent              assign an owner
registry_drift             declare what it uses
undeclared_mcp_tool        declare the tool with an impact · grant it
containment (no grant)     grant · grant with approval · view run · add to tests
containment (unknown tool) declare the tool with an impact · view run
containment (other)        view run · add to tests · not a problem
guardrail_detection        add to tests · not a problem · suppress for this agent ·
                           tune threshold · view run
agent_stopped              resume
budget_breach              open checks (closes itself on recovery)
grounding and quality      view run · add to tests · not a problem
hand-off types             open the conversation
red-team types             run attack test
drift / over-refusal /
boundary breach            quality tab / what it may answer
monitor / skill / MCP      open sources
delegation                 open the map
=========================  ==================================================
"""

from __future__ import annotations

import datetime as dt
import fnmatch
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import (
    Agent,
    Capability,
    Credential,
    Decision,
    Finding,
    Identity,
    LineageEdge,
    Tool,
    Trace,
    utcnow,
)
from agentfox.platform.identity import ensure_identity
from agentfox.platform.identity.service import (
    assess_identity,
    grant_capability,
    revoke_capability,
    revoke_credential,
)
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.findings import OPEN, resolve_finding
from agentfox.platform.ledger.operator_log import record
from agentfox.platform.registry.control import set_state, state_of
from agentfox.platform.registry.impact import infer_impact
from agentfox.platform.registry.service import impact_source_of, register_agent, upsert_tool

#: Who closes a finding whose condition cleared after a remedy.
SYSTEM_ACTOR = "agentfox.remediation"
IMPACTS = ("read", "write", "high_impact", "irreversible")
IMPACT_LABELS = {
    "read": "Read only",
    "write": "Writes data",
    "high_impact": "High impact",
    "irreversible": "Irreversible",
}
#: How far back "the tools it uses" looks when narrowing a wildcard grant.
USED_WINDOW_DAYS = 30
SUPPRESSION_DAYS = 30

_INJECTION_PREFIXES = ("INJECTION", "JAILBREAK")
_GROUNDING_TYPES = {
    "boundary_breach",
    "source_authority",
    "fabricated_citation",
    "source_conflict",
    "integrity_error",
    "entitlement_disclosure",
    "aggregation_disclosure",
    "inference_disclosure",
    "binding_commitment",
    "register_breach",
    "ai_impersonation",
    "ai_disclosure_missing",
    "adverse_action",
    "sycophancy",
    "context_integrity",
    "control_flow",
    "trajectory_drift",
    "budget_exhausted",
    "agent_loop_stopped",
}
_HANDOFF_TYPES = {
    "missed_escalation",
    "handoff_sla_breach",
    "incomplete_handoff",
    "false_resolution",
}
_REDTEAM_TYPES = {
    "redteam",
    "redteam_over_block",
    "redteam_mutation_class",
    "redteam_posture_regression",
    "live_probe_escape",
}
_SOURCE_TYPES_PREFIX = ("monitor_", "skill_")
_SOURCE_TYPES = {
    "schema_drift",
    "tool_poisoning",
    "unpinned_server",
    "mcp_schema_drift",
    "mcp_tool_added_under_wildcard",
}


class RemedyError(ValueError):
    """The remedy does not apply to this finding now, or its input is incomplete."""


@dataclass(frozen=True)
class Field:
    """One input an action needs from the person taking it."""

    name: str
    label: str
    kind: str = "text"  # text | email | select
    required: bool = True
    options: tuple[tuple[str, str], ...] = ()
    placeholder: str = ""
    default: str = ""


@dataclass(frozen=True)
class Remedy:
    key: str
    label: str
    kind: str = "action"  # action | link
    #: The permission family an action needs (`WRITE_ROLES` in the gateway);
    #: "feedback" is open to every role that may label a decision.
    family: str | None = None
    href: str | None = None
    fields: tuple[Field, ...] = ()
    confirm: str = ""
    primary: bool = False
    #: One line on what the action does, shown beside it.
    hint: str = ""

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["fields"] = [
            {**asdict(f), "options": [{"value": v, "label": label} for v, label in f.options]}
            for f in self.fields
        ]
        return out


@dataclass
class _Ctx:
    finding: Finding
    evidence: dict[str, Any]
    agent: Agent | None
    identity: Identity | None
    decision: Decision | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def slug(self) -> str | None:
        return self.agent.slug if self.agent else None


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def _agent_by_ref(session: Session, ref: str | None) -> Agent | None:
    if not ref:
        return None
    return session.get(Agent, ref) or session.scalar(select(Agent).where(Agent.slug == ref))


def _context(session: Session, finding: Finding) -> _Ctx:
    evidence = dict(finding.evidence_json or {})
    agent: Agent | None = None
    identity: Identity | None = None
    if finding.subject_type == "agent":
        agent = _agent_by_ref(session, finding.subject_id)
    elif finding.subject_type == "identity" and finding.subject_id:
        identity = session.get(Identity, finding.subject_id)
        agent = session.get(Agent, identity.agent_id) if identity and identity.agent_id else None
    if agent is None:
        agent = _agent_by_ref(session, evidence.get("agent") or evidence.get("slug"))
    if identity is None and agent is not None:
        identity = session.scalar(select(Identity).where(Identity.agent_id == agent.id))
    decision = (
        session.get(Decision, evidence["decision_id"]) if evidence.get("decision_id") else None
    )
    return _Ctx(finding, evidence, agent, identity, decision)


def _grants(identity: Identity | None) -> list[Capability]:
    if identity is None:
        return []
    return [c for c in identity.capabilities if not c.tool_key.startswith("redteam.")]


def _covering(identity: Identity | None, tool_key: str) -> Capability | None:
    return next((c for c in _grants(identity) if fnmatch.fnmatch(tool_key, c.tool_key)), None)


def _used_tools(session: Session, agent: Agent | None) -> list[str]:
    if agent is None:
        return []
    since = utcnow() - dt.timedelta(days=USED_WINDOW_DAYS)
    used = {
        k
        for k in session.scalars(
            select(Decision.tool_key)
            .where(
                Decision.agent_id == agent.id,
                Decision.created_at >= since,
                Decision.tool_key.is_not(None),
            )
            .distinct()
        )
        if k and not k.startswith("redteam.")
    }
    return sorted(used | set(agent.declared_tools or []))


def _detector_rule(decision: Decision | None) -> str | None:
    """The rule that tested detections on this decision: the one a threshold tunes."""
    for fired in (decision.rules_fired_json or []) if decision else []:
        if isinstance(fired, dict) and (fired.get("entities") or fired.get("entity_prefixes")):
            return fired.get("rule_id")
    return None


def _impact_field(default: str = "") -> Field:
    return Field(
        "impact",
        "Impact",
        kind="select",
        options=tuple((k, IMPACT_LABELS[k]) for k in IMPACTS),
        default=default,
    )


def _reason_field(placeholder: str) -> Field:
    return Field("reason", "Reason", placeholder=placeholder)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


def _links(ctx: _Ctx) -> list[Remedy]:
    """Places to go that fit most findings: the run, the agent."""
    out: list[Remedy] = []
    if trace_id := ctx.evidence.get("trace_id"):
        out.append(Remedy("view_run", "View run", kind="link", href=f"/app/traces/{trace_id}"))
    return out


def _test_and_feedback(session: Session, ctx: _Ctx, *, primary_test: bool = False) -> list[Remedy]:
    out: list[Remedy] = []
    trace_id = ctx.evidence.get("trace_id")
    if trace_id and session.get(Trace, trace_id) is not None:
        out.append(
            Remedy(
                "add_to_tests",
                "Add to tests",
                family="eval",
                primary=primary_test,
                hint="Adds this run to the Regressions suite so it is checked before release.",
            )
        )
    if ctx.decision is not None:
        out.append(
            Remedy(
                "false_positive",
                "Not a problem",
                family="feedback",
                fields=(Field("note", "Why", required=False, placeholder="Why it was fine"),),
                hint="Records a false positive for tuning and closes this issue.",
            )
        )
    return out


def _over_privileged(session: Session, ctx: _Ctx) -> list[Remedy]:
    wildcard = [c for c in _grants(ctx.identity) if c.tool_key.strip() == "*"]
    if not wildcard:
        return []
    used = _used_tools(session, ctx.agent)
    out = []
    if used:
        names = ", ".join(used[:4]) + (f" and {len(used) - 4} more" if len(used) > 4 else "")
        out.append(
            Remedy(
                "narrow_wildcard",
                f"Replace * with its {len(used)} tools",
                family="identity",
                primary=True,
                hint=f"Grants {names} by name, then revokes *.",
            )
        )
    out.append(
        Remedy(
            "revoke_wildcard",
            "Revoke *",
            family="identity",
            primary=not used,
            confirm="Revoke the * grant? Tools without their own grant will be refused.",
            hint="Tools without their own grant will be refused.",
        )
    )
    return out


def _identity_hygiene(session: Session, ctx: _Ctx) -> list[Remedy]:
    if ctx.identity is None or ctx.identity.status != "active":
        return []
    out = []
    grants = _grants(ctx.identity)
    if ctx.finding.type == "stale_identity" and grants:
        out.append(
            Remedy(
                "revoke_grants",
                f"Revoke its {len(grants)} grants",
                family="identity",
                primary=True,
                confirm="Revoke every grant this identity holds?",
                hint="Keeps the identity; it can call nothing until granted again.",
            )
        )
    out.append(
        Remedy(
            "retire_identity",
            "Retire identity",
            family="identity",
            primary=ctx.finding.type == "orphaned_identity",
            confirm="Retire this identity? Its keys stop working and its grants are removed.",
            hint="Revokes its keys and grants. It can no longer authenticate.",
        )
    )
    return out


def _shadow(session: Session, ctx: _Ctx) -> list[Remedy]:
    if ctx.agent is None:
        return []
    out = []
    if not ctx.agent.registered:
        out.append(
            Remedy(
                "register",
                "Register agent",
                family="registry",
                primary=True,
                fields=(
                    Field(
                        "owner_email",
                        "Owner",
                        kind="email",
                        required=False,
                        placeholder="owner@company.com",
                    ),
                ),
                hint="Adds it to the registry with the models it was seen using.",
            )
        )
    if state_of(session, ctx.agent.slug) == "active":
        out.append(
            Remedy(
                "block_agent",
                "Block agent",
                family="identity",
                fields=(_reason_field("Why it should not run"),),
                confirm="Block this agent? Every call from it will be refused.",
                hint="Refuses every call from it until resumed.",
            )
        )
    return out


def _unowned(session: Session, ctx: _Ctx) -> list[Remedy]:
    if ctx.agent is None or ctx.agent.is_owned:
        return []
    return [
        Remedy(
            "assign_owner",
            "Assign owner",
            family="registry",
            primary=True,
            fields=(
                Field("owner_email", "Owner", kind="email", placeholder="owner@company.com"),
                Field("owner_team", "Team", required=False, placeholder="Team"),
            ),
        )
    ]


def _drift(session: Session, ctx: _Ctx) -> list[Remedy]:
    if ctx.agent is None:
        return []
    tools, models = _undeclared(session, ctx.agent)
    if not tools and not models:
        return []
    parts = [f"{len(tools)} tools"] if tools else []
    parts += [f"{len(models)} models"] if models else []
    return [
        Remedy(
            "declare_used",
            f"Declare {' and '.join(parts)}",
            family="registry",
            primary=True,
            hint="Adds " + ", ".join([*tools, *models][:5]) + " to what this agent declares.",
        )
    ]


def _undeclared(session: Session, agent: Agent) -> tuple[list[str], list[str]]:
    observed_models = {
        t.model
        for t in session.scalars(select(Trace).where(Trace.agent_slug == agent.slug))
        if t.model
    }
    observed_tools = {
        e.dst_id
        for e in session.scalars(
            select(LineageEdge).where(
                LineageEdge.src_id == agent.slug, LineageEdge.relation == "calls_tool"
            )
        )
    }
    return (
        sorted(observed_tools - set(agent.declared_tools or [])),
        sorted(observed_models - set(agent.declared_models or [])),
    )


def _tool_key(ctx: _Ctx) -> str | None:
    return ctx.evidence.get("key") or ctx.evidence.get("tool")


def _declare_tool(session: Session, ctx: _Ctx, *, primary: bool) -> list[Remedy]:
    key = _tool_key(ctx)
    if not key:
        return []
    tool = session.scalar(select(Tool).where(Tool.key == key))
    guess = tool.impact if tool else infer_impact(key, cautious=True)
    return [
        Remedy(
            "declare_tool",
            "Declare tool",
            family="registry",
            primary=primary,
            fields=(_impact_field(guess),),
            hint=f"Registers {key} with the impact you choose"
            + (" and adds it to what this agent declares." if ctx.agent else "."),
        )
    ]


def _grant_tool(session: Session, ctx: _Ctx, *, primary: bool) -> list[Remedy]:
    key = _tool_key(ctx)
    if not key or ctx.agent is None or _covering(ctx.identity, key) is not None:
        return []
    return [
        Remedy(
            "grant",
            f"Grant {key}",
            family="identity",
            primary=primary,
            hint="Lets this agent call it.",
        ),
        Remedy(
            "grant_with_approval",
            "Grant with approval",
            family="identity",
            hint="Each call waits for a person to approve it.",
        ),
    ]


def _containment(session: Session, ctx: _Ctx) -> list[Remedy]:
    cause = ctx.evidence.get("cause")
    out: list[Remedy] = []
    if cause == "no_permission":
        out += _grant_tool(session, ctx, primary=True)
    elif cause == "unknown_tool":
        out += _declare_tool(session, ctx, primary=True)
    out += _test_and_feedback(session, ctx)
    return out + _links(ctx)


def _detection(session: Session, ctx: _Ctx) -> list[Remedy]:
    entities = [str(d.get("entity_type") or "") for d in ctx.evidence.get("detections") or []]
    attack = any(e.upper().startswith(_INJECTION_PREFIXES) for e in entities)
    out = _test_and_feedback(session, ctx, primary_test=attack)
    decision = ctx.decision
    if decision is not None and decision.detector_run_ids and ctx.agent is not None:
        out.append(
            Remedy(
                "suppress_for_agent",
                "Suppress for this agent",
                family="suppressions",
                fields=(_reason_field("Why this is noise for this agent"),),
                hint=f"Stops this detector flagging this kind of content for this agent for "
                f"{SUPPRESSION_DAYS} days.",
            )
        )
    if (rule := _detector_rule(decision)) and ctx.slug:
        out.append(
            Remedy(
                "tune_threshold",
                "Tune threshold",
                kind="link",
                href=f"/app/policies/rules/{quote(rule, safe='')}?"
                + urlencode({"tab": "tune", "agent": ctx.slug}),
            )
        )
    return out + _links(ctx)


def _stopped(session: Session, ctx: _Ctx) -> list[Remedy]:
    if ctx.agent is None or state_of(session, ctx.agent.slug) == "active":
        return []
    return [
        Remedy(
            "resume_agent",
            "Resume agent",
            family="identity",
            primary=True,
            fields=(_reason_field("What was dealt with"),),
        )
    ]


def _agent_tab(ctx: _Ctx, tab: str) -> str:
    return f"/app/agents/{quote(ctx.slug or '', safe='')}?tab={tab}"


def remedies_for(session: Session, finding: Finding) -> list[Remedy]:
    """Every remedy that applies to this finding now. Links only once it is closed."""
    ctx = _context(session, finding)
    t = finding.type
    out: list[Remedy] = []
    if t == "over_privileged":
        out = _over_privileged(session, ctx)
    elif t in ("stale_identity", "orphaned_identity"):
        out = _identity_hygiene(session, ctx)
    elif t == "shadow_agent":
        out = _shadow(session, ctx)
    elif t == "unowned_agent":
        out = _unowned(session, ctx)
    elif t == "registry_drift":
        out = _drift(session, ctx)
    elif t == "undeclared_mcp_tool":
        out = _declare_tool(session, ctx, primary=True) + _grant_tool(session, ctx, primary=False)
    elif t == "containment":
        out = _containment(session, ctx)
    elif t == "guardrail_detection":
        out = _detection(session, ctx)
    elif t == "agent_stopped":
        out = _stopped(session, ctx)
    elif t == "budget_breach":
        out = [Remedy("open_checks", "Open Checks", kind="link", href="/app/policies?tab=checks")]
    elif t in _GROUNDING_TYPES:
        out = _test_and_feedback(session, ctx) + _links(ctx)
        if t == "boundary_breach" and ctx.slug:
            out.append(
                Remedy(
                    "edit_boundary",
                    "Edit what it may answer",
                    kind="link",
                    href=_agent_tab(ctx, "access"),
                )
            )
    elif t in _HANDOFF_TYPES:
        sid = ctx.evidence.get("session_id")
        href = (
            f"/app/escalation/conversations/{quote(str(sid), safe='')}"
            if sid
            else "/app/escalation"
        )
        out = [Remedy("open_conversation", "Open conversation", kind="link", href=href)]
    elif t in _REDTEAM_TYPES:
        out = [
            Remedy("run_attack_test", "Run attack test", kind="link", href="/app/test?tab=attacks")
        ]
    elif t == "drift" and ctx.slug:
        out = [Remedy("open_quality", "Open quality", kind="link", href=_agent_tab(ctx, "quality"))]
    elif t == "over_refusal" and ctx.slug:
        out = [
            Remedy(
                "edit_boundary",
                "Edit what it may answer",
                kind="link",
                href=_agent_tab(ctx, "access"),
            )
        ]
    elif t in _SOURCE_TYPES or t.startswith(_SOURCE_TYPES_PREFIX):
        out = [Remedy("open_sources", "Open sources", kind="link", href="/app/sources")]
    elif t in ("delegation_cycle", "delegation_depth"):
        out = [
            Remedy(
                "open_map",
                "Open map",
                kind="link",
                href=f"/app/map?agent={quote(ctx.slug, safe='')}" if ctx.slug else "/app/map",
            )
        ]
    else:
        out = _links(ctx)
    if finding.status != OPEN:
        out = [r for r in out if r.kind == "link"]
    return out


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------


def _audit_grant(session: Session, event: str, cap: Capability, slug: str, actor: str) -> None:
    chain.append(
        session,
        event,
        actor_type="user",
        actor_id=actor,
        subject_type="capability",
        subject_id=cap.id,
        payload={
            "agent": slug,
            "tool_key": cap.tool_key,
            "requires_approval": cap.requires_approval,
            "max_taint": cap.max_taint,
            "constraints": cap.constraints_json or {},
            "via": "finding",
        },
    )


def _revoke(session: Session, cap: Capability, slug: str, actor: str) -> None:
    _audit_grant(session, "capability.revoked", cap, slug, actor)
    revoke_capability(session, cap.id)


def _do_narrow(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    identity = ctx.identity
    wildcard = [c for c in _grants(identity) if c.tool_key.strip() == "*"]
    named = {c.tool_key for c in _grants(identity)}
    used = _used_tools(session, ctx.agent)
    slug = ctx.slug or ""
    for key in used:
        if key in named:
            continue
        template = wildcard[0]
        cap = grant_capability(
            session,
            identity,
            key,
            actions=list(template.actions or ["*"]),
            constraints=dict(template.constraints_json or {}),
            requires_approval=template.requires_approval,
            max_taint=template.max_taint,
            granted_by=actor,
        )
        _audit_grant(session, "capability.granted", cap, slug, actor)
    for cap in wildcard:
        _revoke(session, cap, slug, actor)
    session.refresh(identity)
    return f"Granted {len(used)} tools by name and revoked *."


def _do_revoke_wildcard(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    for cap in [c for c in _grants(ctx.identity) if c.tool_key.strip() == "*"]:
        _revoke(session, cap, ctx.slug or "", actor)
    session.refresh(ctx.identity)
    return "Revoked *."


def _do_revoke_grants(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    grants = _grants(ctx.identity)
    for cap in grants:
        _revoke(session, cap, ctx.slug or "", actor)
    session.refresh(ctx.identity)
    return f"Revoked {len(grants)} grants."


def _do_retire(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    identity = ctx.identity
    keys = 0
    for credential in session.scalars(
        select(Credential).where(
            Credential.identity_id == identity.id, Credential.revoked_at.is_(None)
        )
    ):
        revoke_credential(session, credential.id)
        keys += 1
    grants = _grants(identity)
    for cap in grants:
        _revoke(session, cap, ctx.slug or "", actor)
    identity.status = "retired"
    session.flush()
    chain.append(
        session,
        "identity.retired",
        actor_type="user",
        actor_id=actor,
        subject_type="identity",
        subject_id=identity.id,
        payload={"principal": identity.principal, "keys_revoked": keys, "grants": len(grants)},
    )
    session.refresh(identity)
    return f"Retired the identity: {keys} keys and {len(grants)} grants revoked."


def _do_register(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    agent = ctx.agent
    suggested = ctx.evidence.get("suggested_registration") or {}
    models = sorted(
        {
            *(suggested.get("declared_models") or []),
            *(
                t.model
                for t in session.scalars(select(Trace).where(Trace.agent_slug == agent.slug))
                if t.model
            ),
        }
    )
    register_agent(
        session,
        agent.slug,
        name=agent.name or agent.slug,
        environment=agent.environment,
        risk_tier=agent.risk_tier or "limited",
        owner_email=(inputs.get("owner_email") or "").strip() or None,
        declared_models=models,
        framework=agent.framework,
    )
    chain.append(
        session,
        "agent.registered",
        actor_type="user",
        actor_id=actor,
        subject_type="agent",
        subject_id=agent.id,
        payload={"slug": agent.slug, "declared_models": models, "via": "finding"},
    )
    return f"Registered {agent.slug}."


def _do_block(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    reason = str(inputs["reason"]).strip()
    set_state(session, ctx.agent.slug, "killed", reason=reason, actor=actor)
    return f"Blocked {ctx.agent.slug}."


def _do_resume(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    set_state(session, ctx.agent.slug, "active", reason=str(inputs["reason"]).strip(), actor=actor)
    return f"Resumed {ctx.agent.slug}."


def _do_owner(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    agent = ctx.agent
    owner = str(inputs["owner_email"]).strip()
    if "@" not in owner:
        raise RemedyError("owner must be an email address")
    changes: dict[str, Any] = {"owner_email": owner}
    if team := str(inputs.get("owner_team") or "").strip():
        changes["owner_team"] = team
    for name, value in changes.items():
        setattr(agent, name, value)
    session.flush()
    chain.append(
        session,
        "agent.updated",
        actor_type="user",
        actor_id=actor,
        subject_type="agent",
        subject_id=agent.id,
        payload={**changes, "via": "finding"},
    )
    return f"{owner} now owns {agent.slug}."


def _do_declare_used(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    agent = ctx.agent
    tools, models = _undeclared(session, agent)
    agent.declared_tools = sorted({*(agent.declared_tools or []), *tools})
    agent.declared_models = sorted({*(agent.declared_models or []), *models})
    session.flush()
    chain.append(
        session,
        "agent.updated",
        actor_type="user",
        actor_id=actor,
        subject_type="agent",
        subject_id=agent.id,
        payload={"declared_tools_added": tools, "declared_models_added": models, "via": "finding"},
    )
    return f"Declared {len(tools)} tools and {len(models)} models."


def _do_declare_tool(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    key = _tool_key(ctx)
    impact = str(inputs["impact"])
    if impact not in IMPACTS:
        raise RemedyError(f"impact must be one of {', '.join(IMPACTS)}")
    known = session.scalar(select(Tool).where(Tool.key == key))
    upsert_tool(session, key, impact=impact, actor=actor, name=(known.name if known else "") or key)
    agent = ctx.agent
    if agent is not None and key not in (agent.declared_tools or []):
        agent.declared_tools = sorted({*(agent.declared_tools or []), key})
        session.flush()
        chain.append(
            session,
            "agent.updated",
            actor_type="user",
            actor_id=actor,
            subject_type="agent",
            subject_id=agent.id,
            payload={"declared_tools_added": [key], "via": "finding"},
        )
    return f"Declared {key} as {IMPACT_LABELS[impact].lower()}."


def _grant(session: Session, ctx: _Ctx, actor: str, approval: bool) -> str:
    key = _tool_key(ctx)
    if session.scalar(select(Tool).where(Tool.key == key)) is None:
        # A grant for a tool the registry has never seen would leave every call held as
        # undeclared: register it with a cautious guess for someone to confirm.
        upsert_tool(
            session,
            key,
            impact=infer_impact(key, cautious=True),
            impact_source="inferred",
            actor=actor,
        )
    identity = ensure_identity(session, ctx.agent)
    existing = next((c for c in identity.capabilities if c.tool_key == key), None)
    if existing is not None:
        existing.requires_approval = approval
        cap, event = existing, "capability.updated"
        session.flush()
    else:
        cap = grant_capability(session, identity, key, requires_approval=approval, granted_by=actor)
        event = "capability.granted"
    _audit_grant(session, event, cap, ctx.agent.slug, actor)
    session.refresh(identity)
    ctx.identity = identity
    return f"Granted {key}" + (" with approval." if approval else ".")


def _do_false_positive(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    from agentfox.capabilities.detection.tuning import record_feedback

    note = str(inputs.get("note") or "").strip()
    record_feedback(
        session, decision_id=ctx.decision.id, label="false_positive", note=note, actor=actor
    )
    resolve_finding(
        session, ctx.finding, actor=actor, note="Not a problem: " + (note or "false positive")
    )
    return "Recorded as a false positive."


def _do_suppress(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    from agentfox.capabilities.detection.tuning import apply_suppression, record_feedback

    reason = str(inputs["reason"]).strip()
    feedback = record_feedback(
        session, decision_id=ctx.decision.id, label="false_positive", note=reason, actor=actor
    )
    try:
        apply_suppression(
            session,
            feedback_id=feedback.id,
            scope="agent",
            ttl_days=SUPPRESSION_DAYS,
            actor=actor,
            reason=reason,
        )
    except ValueError as exc:
        raise RemedyError(str(exc)) from exc
    resolve_finding(
        session,
        ctx.finding,
        actor=actor,
        note=f"Suppressed for {ctx.slug} for {SUPPRESSION_DAYS} days: {reason}",
    )
    return f"Suppressed for this agent for {SUPPRESSION_DAYS} days."


def _do_add_to_tests(session: Session, ctx: _Ctx, actor: str, inputs: dict[str, Any]) -> str:
    from agentfox.capabilities.evaluation.cases import (
        REGRESSIONS_SUITE,
        ensure_suite,
        promote_trace,
    )

    suite = ensure_suite(
        session,
        REGRESSIONS_SUITE,
        name="Regressions",
        description="Runs added from issues, checked before release.",
    )
    try:
        promote_trace(session, suite, ctx.evidence["trace_id"], actor=actor)
    except LookupError as exc:
        raise RemedyError(str(exc)) from exc
    return "Added to the Regressions suite."


_HANDLERS: dict[str, Callable[[Session, _Ctx, str, dict[str, Any]], str]] = {
    "narrow_wildcard": _do_narrow,
    "revoke_wildcard": _do_revoke_wildcard,
    "revoke_grants": _do_revoke_grants,
    "retire_identity": _do_retire,
    "register": _do_register,
    "block_agent": _do_block,
    "resume_agent": _do_resume,
    "assign_owner": _do_owner,
    "declare_used": _do_declare_used,
    "declare_tool": _do_declare_tool,
    "grant": lambda s, c, a, i: _grant(s, c, a, approval=False),
    "grant_with_approval": lambda s, c, a, i: _grant(s, c, a, approval=True),
    "false_positive": _do_false_positive,
    "suppress_for_agent": _do_suppress,
    "add_to_tests": _do_add_to_tests,
}


def find_remedy(session: Session, finding: Finding, key: str) -> Remedy:
    """The action ``key`` if it applies to this finding now; `RemedyError` otherwise."""
    if finding.status != OPEN:
        raise RemedyError("this issue is not open")
    remedy = next(
        (r for r in remedies_for(session, finding) if r.key == key and r.kind == "action"), None
    )
    if remedy is None or key not in _HANDLERS:
        raise RemedyError(f"'{key}' does not apply to this issue now")
    return remedy


def apply_remedy(
    session: Session,
    finding: Finding,
    key: str,
    *,
    actor: str,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Take one action on an issue, record it, and close the issue if that fixed it.

    The finding is re-checked against the live state afterwards: when the condition it
    is about no longer holds it is resolved automatically, under the system's name with
    the action named in the note. An action that does not clear the condition (adding
    a run to the tests) leaves it open.
    """
    inputs = {k: v for k, v in (inputs or {}).items() if v not in (None, "")}
    remedy = find_remedy(session, finding, key)
    missing = [
        f.label for f in remedy.fields if f.required and not str(inputs.get(f.name, "")).strip()
    ]
    if missing:
        raise RemedyError(f"{', '.join(missing)} required")
    ctx = _context(session, finding)
    message = _HANDLERS[key](session, ctx, actor, inputs)
    record(
        session,
        "operator.finding.remedied",
        actor=actor,
        reason=str(
            inputs.get("reason") or inputs.get("note") or f"{remedy.label}: {finding.title}"
        ),
        subject_type="finding",
        subject_id=finding.id,
        after={"remedy": key, "type": finding.type, "result": message, "inputs": inputs},
    )
    holds = recheck(session, finding, after=remedy.label)
    # One action can clear another issue about the same subject (registering a shadow
    # agent with an owner also answers "no owner"): re-check those too.
    for sibling in session.scalars(
        select(Finding).where(
            Finding.subject_type == finding.subject_type,
            Finding.subject_id == finding.subject_id,
            Finding.status == OPEN,
            Finding.id != finding.id,
        )
    ).all():
        recheck(session, sibling, after=f"{remedy.label} on another issue")
    return {
        "remedy": key,
        "message": message,
        "status": finding.status,
        "resolved": finding.status != OPEN,
        "condition_holds": holds,
    }


# ---------------------------------------------------------------------------
# Re-checking
# ---------------------------------------------------------------------------


def _holds(session: Session, ctx: _Ctx) -> bool | None:
    """Whether the finding's condition still holds. None when it cannot be told here."""
    f = ctx.finding
    t = f.type
    if t in ("over_privileged", "stale_identity", "orphaned_identity"):
        if ctx.identity is None:
            return None
        found = assess_identity(session, ctx.identity)
        return found is not None and found.type == t
    if ctx.agent is None:
        return None
    if t == "shadow_agent":
        return not ctx.agent.registered and state_of(session, ctx.agent.slug) == "active"
    if t == "unowned_agent":
        return not ctx.agent.is_owned
    if t == "registry_drift":
        tools, models = _undeclared(session, ctx.agent)
        return bool(tools or models)
    if t == "agent_stopped":
        return state_of(session, ctx.agent.slug) != "active"
    key = _tool_key(ctx)
    if t == "undeclared_mcp_tool" and key:
        return key not in (ctx.agent.declared_tools or [])
    if t == "containment" and key:
        cause = ctx.evidence.get("cause")
        if cause == "no_permission":
            identity = session.scalar(select(Identity).where(Identity.agent_id == ctx.agent.id))
            return _covering(identity, key) is None
        if cause == "unknown_tool":
            tool = session.scalar(select(Tool).where(Tool.key == key))
            return tool is None or impact_source_of(tool) == "inferred"
    return None


def recheck(session: Session, finding: Finding, *, after: str = "") -> bool | None:
    """Re-test an open finding's condition and close it if it cleared.

    Returns whether the condition still holds (None: not checkable here).
    """
    if finding.status != OPEN:
        return False
    holds = _holds(session, _context(session, finding))
    if holds is False and finding.status == OPEN:
        resolve_finding(
            session,
            finding,
            actor=SYSTEM_ACTOR,
            note=f"Condition cleared after: {after}" if after else "Condition cleared",
            automated=True,
        )
    return holds


__all__ = [
    "IMPACTS",
    "Field",
    "Remedy",
    "RemedyError",
    "apply_remedy",
    "find_remedy",
    "recheck",
    "remedies_for",
]
