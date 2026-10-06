"""Entitlement and disclosure control. The highest commercial-value gap.

The Copilot research names the failure precisely: *"a governance failure rather than a
security breach — **every permission check passed**."* The agent runs under its own
service identity and inherits the union of everything that identity can reach. One
prompt — *"summarise our M&A discussions last quarter"* — surfaces everything the
service account can read, and every ACL in the path returns allow, because nobody
asked what **this requesting human** was entitled to see.

That is why Copilot-class rollouts stall, and it is the failure the four business
examples that started this project led with: *the agent has an SDK for information
that must not be given.*

Three things make this tractable without asking a customer to rebuild their
permissions model first:

* **The principal is propagated, not inferred.** Propagation is the dependency
  for everything else, and it is a plumbing problem rather than a modelling one.
* **The engine is a seam.** Customers running OpenFGA, Cedar or SpiceDB keep them.
  The native ACL exists because the much larger group express permissions as "this
  group can read this folder" and nothing more formal, and a control that requires a
  relationship model first is a control they will never switch on.
* **The diagnostic works with no entitlement model at all.** The over-permission
  report compares what the agent could reach against what the principal is entitled
  to. A customer with zero grants configured still learns their over-permission
  ratio, which is the number that motivates doing the rest.

**Withholding is recorded, never silent.** A pre-filter that quietly returns fewer
chunks tells nobody anything. The drop count *is* the oversharing metric.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import DisclosureEvent, EndUserPrincipal, ResourceGrant, utcnow

log = logging.getLogger(__name__)

#: Classes that are never disclosed on entitlement alone — they need an explicit
#: clearance. Material non-public information and legal holds are the cases where
#: "the user could technically read the folder" is not the question anyone is asking.
RESTRICTED_CLASSES = ("mnpi", "legal_hold", "blackout", "insider", "pii_sensitive")

#: Below this many contributing records, an aggregate identifies individuals. Salary
#: band plus a headcount of one is one person's salary, however aggregated it looks.
DEFAULT_K_ANONYMITY = 5


@runtime_checkable
class EntitlementEngine(Protocol):
    """The swappable seam. No winner exists, so we build the seam."""

    key: str

    def available(self) -> bool: ...

    def visible(
        self, session: Session, principal: EndUserPrincipal, resources: list[str]
    ) -> set[str]:
        """Which of these resources the principal may see."""
        ...


# ---------------------------------------------------------------------------
# Principals
# ---------------------------------------------------------------------------


def upsert_principal(
    session: Session,
    subject: str,
    *,
    agent_id: str | None = None,
    display: str = "",
    groups: list[str] | None = None,
    clearances: list[str] | None = None,
    purposes: list[str] | None = None,
    residency: str | None = None,
) -> EndUserPrincipal:
    record = session.scalar(
        select(EndUserPrincipal).where(
            EndUserPrincipal.subject == subject, EndUserPrincipal.agent_id == agent_id
        )
    )
    if record is None:
        record = EndUserPrincipal(subject=subject, agent_id=agent_id)
        session.add(record)
    record.display = display or record.display
    record.groups = groups if groups is not None else (record.groups or [])
    record.clearances = clearances if clearances is not None else (record.clearances or [])
    record.purposes = purposes if purposes is not None else (record.purposes or [])
    record.residency = residency or record.residency
    record.last_seen_at = utcnow()
    session.flush()
    return record


def grant(
    session: Session,
    resource: str,
    *,
    principal: str,
    principal_kind: str = "group",
    classes: list[str] | None = None,
    purposes: list[str] | None = None,
    residency: str | None = None,
) -> ResourceGrant:
    record = ResourceGrant(
        resource=resource,
        principal=principal,
        principal_kind=principal_kind,
        classes=classes or [],
        purposes=purposes or [],
        residency=residency,
    )
    session.add(record)
    session.flush()
    return record


# ---------------------------------------------------------------------------
# The native engine
# ---------------------------------------------------------------------------


class NativeAclEngine:
    """Glob-matched grants over groups and subjects.

    Default-deny: a resource with no grant is invisible. That is the only safe default
    — the alternative silently discloses anything nobody remembered to protect, which
    is the failure this pillar exists to prevent.
    """

    key = "native"

    def available(self) -> bool:
        return True

    def visible(
        self, session: Session, principal: EndUserPrincipal, resources: list[str]
    ) -> set[str]:
        if not resources:
            return set()
        grants = list(session.scalars(select(ResourceGrant)))
        identities = {("subject", principal.subject)}
        identities |= {("group", g) for g in (principal.groups or [])}

        allowed: set[str] = set()
        for resource in resources:
            for record in grants:
                if (record.principal_kind, record.principal) not in identities:
                    continue
                if not fnmatch.fnmatch(resource, record.resource):
                    continue
                # A grant does not override a restricted class; that needs a clearance.
                blocked = set(record.classes or []) - set(principal.clearances or [])
                if blocked & set(RESTRICTED_CLASSES):
                    continue
                allowed.add(resource)
                break
        return allowed


class OpenFgaEngine:
    """Entitlement lookup via OpenFGA `ListObjects`. Apache-2.0, CNCF incubating.

    Reports unavailable without the SDK and a configured store rather than guessing —
    a permissions engine that improvises is worse than one that is honestly absent.
    """

    key = "openfga"

    def available(self) -> bool:
        from agentfox.core.config import get_settings

        settings = get_settings()
        if not (settings.openfga_url and settings.openfga_store_id):
            return False
        try:
            import openfga_sdk  # noqa: F401
        except ImportError:
            return False
        return True

    def visible(  # pragma: no cover - needs a live OpenFGA
        self, session: Session, principal: EndUserPrincipal, resources: list[str]
    ) -> set[str]:
        raise NotImplementedError(
            "the OpenFGA adapter is a declared seam, not an implementation. "
            "Configure AGENTFOX_ENTITLEMENT_ENGINE=native, or contribute the adapter."
        )


_ENGINES: dict[str, EntitlementEngine] = {}


def register_engine(engine: EntitlementEngine) -> EntitlementEngine:
    _ENGINES[engine.key] = engine
    return engine


def get_engine(key: str | None = None) -> EntitlementEngine:
    from agentfox.core.config import get_settings

    name = key or get_settings().entitlement_engine
    engine = _ENGINES.get(name)
    if engine is None or not engine.available():
        return _ENGINES["native"]
    return engine


register_engine(NativeAclEngine())
register_engine(OpenFgaEngine())


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@dataclass
class DisclosureDecision:
    """What the principal may see, and everything withheld from them."""

    visible: list[dict[str, Any]] = field(default_factory=list)
    withheld: list[dict[str, Any]] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=dict)
    over_permission: float = 0.0
    principal: str | None = None

    @property
    def candidates(self) -> int:
        return len(self.visible) + len(self.withheld)

    def to_json(self) -> dict[str, Any]:
        return {
            "principal": self.principal,
            "candidates": self.candidates,
            "visible": len(self.visible),
            "withheld": len(self.withheld),
            "reasons": self.reasons,
            # The agent's reach beyond the caller's entitlement. Meaningful even
            # with no grants configured, which is the point — it is the diagnostic that
            # motivates building the entitlement model.
            "over_permission": round(self.over_permission, 4),
            "withheld_sources": [w.get("source") for w in self.withheld][:20],
        }


def _classes_for(session: Session, resource: str) -> set[str]:
    classes: set[str] = set()
    for record in session.scalars(select(ResourceGrant)):
        if fnmatch.fnmatch(resource, record.resource):
            classes |= set(record.classes or [])
    return classes


def filter_retrieval(
    session: Session,
    principal: EndUserPrincipal | None,
    chunks: list[dict[str, Any]] | None,
    *,
    purpose: str | None = None,
    engine: EntitlementEngine | None = None,
) -> DisclosureDecision:
    """Remove what this human may not see, and record what was removed.

    With no principal the decision is to disclose nothing new and say so: an agent
    answering with no idea who is asking is exactly the Copilot failure, and silently
    allowing it would make this control decorative.
    """
    chunks = chunks or []
    decision = DisclosureDecision(principal=principal.subject if principal else None)
    if not chunks:
        return decision

    if principal is None:
        decision.withheld = list(chunks)
        decision.reasons = {"no_principal": len(chunks)}
        decision.over_permission = 1.0
        return decision

    engine = engine or get_engine()
    resources = [str(c.get("source") or c.get("id") or "") for c in chunks]
    allowed = engine.visible(session, principal, resources)

    for chunk, resource in zip(chunks, resources, strict=False):
        reason = None
        if resource not in allowed:
            reason = "not_entitled"
        else:
            classes = _classes_for(session, resource)
            missing = (classes & set(RESTRICTED_CLASSES)) - set(principal.clearances or [])
            if missing:
                reason = f"restricted:{sorted(missing)[0]}"
            elif purpose:
                permitted = {
                    p
                    for record in session.scalars(select(ResourceGrant))
                    if fnmatch.fnmatch(resource, record.resource)
                    for p in (record.purposes or [])
                }
                # GDPR Art. 5(1)(b): a resource with declared purposes may only be used
                # for one of them. No declared purpose means unconstrained.
                if permitted and purpose not in permitted:
                    reason = "purpose_limitation"
            if reason is None and principal.residency:
                residencies = {
                    record.residency
                    for record in session.scalars(select(ResourceGrant))
                    if fnmatch.fnmatch(resource, record.resource) and record.residency
                }
                if residencies and principal.residency not in residencies:
                    reason = "residency"

        if reason is None:
            decision.visible.append(chunk)
        else:
            decision.withheld.append(chunk)
            decision.reasons[reason] = decision.reasons.get(reason, 0) + 1

    if decision.candidates:
        decision.over_permission = len(decision.withheld) / decision.candidates
    return decision


def record_disclosure(
    session: Session,
    decision: DisclosureDecision,
    *,
    trace_id: str | None = None,
    agent_id: str | None = None,
    stage: str = "pre",
) -> DisclosureEvent | None:
    """Persist the access check, including the ones that withheld nothing.

    The over-permission ratio is withheld / candidates across every check; recording
    only the checks that withheld something made the denominator exclude every clean
    request and overstated the ratio. Nothing is recorded when there was nothing to
    check (no candidate chunks).
    """
    if not decision.candidates:
        return None
    event = DisclosureEvent(
        trace_id=trace_id,
        agent_id=agent_id,
        principal_subject=decision.principal,
        stage=stage,
        candidates=decision.candidates,
        withheld=len(decision.withheld),
        reasons_json=decision.reasons,
        over_permission=decision.over_permission,
    )
    session.add(event)
    session.flush()
    return event


# ---------------------------------------------------------------------------
# Aggregation and inference
# ---------------------------------------------------------------------------


def aggregation_risk(
    answer: str, *, contributors: int | None = None, k: int = DEFAULT_K_ANONYMITY
) -> dict[str, Any] | None:
    """An aggregate over too few people is not an aggregate.

    Salary band plus a headcount of one is one person's salary, and it passes every
    access check because no individual record was disclosed.
    """
    if contributors is None or contributors >= k:
        return None
    return {
        "kind": "aggregation_disclosure",
        "contributors": contributors,
        "k": k,
        "reason": (
            f"the answer aggregates {contributors} record(s), below the k-anonymity "
            f"threshold of {k} — an aggregate this small identifies individuals"
        ),
    }


#: Attributes a model can infer but a system of record rarely holds. Disclosing these
#: is not a retrieval failure — nothing was retrieved — so no access check can catch it.
_INFERRED_ATTRIBUTES = (
    "pregnan",
    "ethnicit",
    "race",
    "religio",
    "sexual orientation",
    "disabilit",
    "immigration status",
    "political affiliation",
    "union member",
    "health condition",
    "mental health",
    "criminal record",
)


def inference_risk(answer: str, context: str = "") -> dict[str, Any] | None:
    """The model asserting a protected attribute nobody stored.

    Fires only when the claim is *absent from the retrieved context*, which is what
    distinguishes an inference from a lookup: reporting a field the user's own record
    contains is disclosure, and disclosure is what the entitlement filter governs.
    """
    lowered = answer.lower()
    context_lowered = (context or "").lower()
    hits = [a for a in _INFERRED_ATTRIBUTES if a in lowered and a not in context_lowered]
    if not hits:
        return None
    return {
        "kind": "inference_disclosure",
        "attributes": hits,
        "reason": (
            f"the answer asserts protected attribute(s) {hits} that do not appear in the "
            "retrieved context — an inferred attribute is disclosed without ever having "
            "been stored, so no access check governs it"
        ),
    }


def over_permission_report(session: Session, *, days: int = 7) -> dict[str, Any]:
    """How much more the agent can reach than its callers are entitled to.

    Useful before any entitlement model exists, which is the argument for shipping it
    first: a customer with zero grants sees a ratio of 1.0 and understands immediately
    what the exercise is for.
    """
    import datetime as dt

    since = utcnow() - dt.timedelta(days=days)
    events = list(
        session.scalars(select(DisclosureEvent).where(DisclosureEvent.created_at >= since))
    )
    if not events:
        return {
            "window_days": days,
            "requests": 0,
            "over_permission": None,
            "note": (
                "No access checks recorded yet — until the agent is told who's "
                "asking, it can't know whether they're cleared to see the answer."
            ),
        }
    candidates = sum(e.candidates for e in events)
    withheld = sum(e.withheld for e in events)
    reasons: dict[str, int] = {}
    for event in events:
        if not event.withheld:
            continue
        for reason, count in (event.reasons_json or {}).items():
            reasons[reason] = reasons.get(reason, 0) + count
    return {
        "window_days": days,
        "requests": len(events),
        "requests_withholding": sum(1 for e in events if e.withheld),
        "candidates": candidates,
        "withheld": withheld,
        "over_permission": round(withheld / candidates, 4) if candidates else 0.0,
        "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "principals": len({e.principal_subject for e in events if e.principal_subject}),
    }
