"""Framework mapping over the control catalog: coverage, requirements, review and
sign-off (NOM-GOV-02). Part of AgentFox Enterprise (BSL 1.1, see ee/LICENSE).

The catalog itself (controls, mappings as data, obligations) is loaded by the open
core (`agentfox.capabilities.compliance.catalog`); what is here is what turns it into
an auditor's view.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.compliance.catalog import load_catalog
from agentfox.core.models import Control, FrameworkMapping, Obligation, utcnow

FRAMEWORK_TITLES = {
    "eu-ai-act": "EU AI Act",
    "nist-ai-rmf": "NIST AI RMF",
    "iso-42001": "ISO/IEC 42001",
    "soc2": "SOC 2",
    "owasp-llm": "OWASP LLM Top 10",
    "owasp-agentic": "OWASP Agentic Threats",
    "mitre-atlas": "MITRE ATLAS",
}


def review_mapping(
    session: Session,
    control_key: str,
    framework: str,
    reviewer: str,
    reference: str | None = None,
) -> int:
    """Mark mapping(s) reviewed: the step that turns a draft mapping into evidence."""
    query = select(FrameworkMapping).where(
        FrameworkMapping.control_key == control_key, FrameworkMapping.framework == framework
    )
    if reference:
        query = query.where(FrameworkMapping.reference == reference)
    count = 0
    for mapping in session.scalars(query):
        mapping.review_status = "reviewed"
        mapping.reviewed_by = reviewer
        mapping.reviewed_at = utcnow()
        count += 1
    session.flush()
    return count


def sign_off_mapping(
    session: Session,
    control_key: str,
    framework: str,
    reviewer: str,
    reference: str | None = None,
    *,
    actor_id: str | None = None,
) -> int:
    """Record a reviewer's sign-off and its audit-chain entry, as one act.

    The only sign-off path: the web app's review button and `agentfox report signoff`
    both call this, so a sign-off made from either leaves the same
    `compliance.mapping_reviewed` entry. Nothing is appended when no mapping matched.
    """
    from agentfox.platform.ledger import chain

    count = review_mapping(session, control_key, framework, reviewer, reference)
    if count:
        chain.append(
            session,
            "compliance.mapping_reviewed",
            actor_type="user",
            actor_id=actor_id or reviewer,
            subject_type="control",
            subject_id=control_key,
            payload={
                "control_key": control_key,
                "framework": framework,
                "reference": reference,
                "reviewer": reviewer,
                "mappings": count,
            },
        )
    return count


def _review_counts(session: Session, framework: str, keys: set[str]) -> dict[str, int]:
    """How many of a framework's controls carry a current, an expired or no attestation."""
    from agentfox_ee.compliance.reviews import latest_reviews, review_state

    reviews = latest_reviews(session, framework)
    counts = {"current": 0, "expired": 0, "none": 0}
    for key in keys:
        counts[review_state(reviews.get((key, framework)))] += 1
    return counts


def framework_coverage(
    session: Session, framework: str, directory: Path | None = None
) -> dict[str, Any]:
    """Coverage **and declared gaps** — the second half is not optional."""
    from agentfox_ee.compliance.status import posture

    data = load_catalog(directory)
    total_controls = session.scalars(select(Control)).all()
    mappings = list(
        session.scalars(select(FrameworkMapping).where(FrameworkMapping.framework == framework))
    )
    mapped_keys = {m.control_key for m in mappings}
    reviewed = [m for m in mappings if m.review_status == "reviewed"]
    obligations = list(
        session.scalars(
            select(Obligation)
            .where(Obligation.framework == framework)
            .order_by(Obligation.effective_date)
        )
    )
    now = utcnow()
    upcoming = [o for o in obligations if o.effective_date and _aware(o.effective_date) > now]

    return {
        "framework": framework,
        "title": FRAMEWORK_TITLES.get(framework, framework),
        "description": (data.get("frameworks") or {}).get(framework, ""),
        "controls_total": len(total_controls),
        "controls_mapped": len(mapped_keys),
        "references": sorted({m.reference for m in mappings}),
        "requirements": len({m.reference for m in mappings}),
        "mappings_total": len(mappings),
        "mappings_reviewed": len(reviewed),
        "mappings_draft": len(mappings) - len(reviewed),
        "review_status": "reviewed" if mappings and len(reviewed) == len(mappings) else "draft",
        "attestations": _review_counts(session, framework, mapped_keys),
        "status_counts": posture(session, framework)["counts"] if mapped_keys else {},
        "obligations": len(obligations),
        "next_deadline": (
            {
                "reference": upcoming[0].reference,
                "title": upcoming[0].title,
                "effective_date": _aware(upcoming[0].effective_date).isoformat(),
            }
            if upcoming
            else None
        ),
        # Rendered next to every coverage claim in the product.
        "declared_gaps": (data.get("gaps") or {}).get(framework, []),
        "caveat": (
            "Mappings are informed engineering drafts produced from the framework "
            "texts. They are not legal advice and have not been reviewed by "
            "compliance counsel or a certification body. Draft mappings do ship in "
            "evidence packages, labelled DRAFT — UNVERIFIED / NOT LEGAL ADVICE."
        ),
    }


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def all_frameworks(session: Session, directory: Path | None = None) -> list[dict[str, Any]]:
    data = load_catalog(directory)
    keys = list((data.get("frameworks") or FRAMEWORK_TITLES).keys())
    return [framework_coverage(session, key, directory) for key in keys]


def controls_for_framework(session: Session, framework: str) -> list[dict[str, Any]]:
    """Each control mapped to the framework, with its live status and attestation."""
    from agentfox_ee.compliance.reviews import latest_reviews, review_json
    from agentfox_ee.compliance.status import latest_statuses

    mappings = list(
        session.scalars(select(FrameworkMapping).where(FrameworkMapping.framework == framework))
    )
    by_control: dict[str, list[FrameworkMapping]] = {}
    for mapping in mappings:
        by_control.setdefault(mapping.control_key, []).append(mapping)
    statuses = latest_statuses(session)
    reviews = latest_reviews(session, framework)

    out: list[dict[str, Any]] = []
    for key, group in sorted(by_control.items()):
        control = session.scalar(select(Control).where(Control.key == key))
        if control is None:
            continue
        status = statuses.get(key)
        out.append(
            {
                "key": key,
                "title": control.title,
                "pillar": control.pillar,
                "implemented_by": control.implemented_by,
                "references": [m.reference for m in group],
                "status": status.status if status else "not_computed",
                "rationale": status.rationale if status else None,
                "review": review_json(reviews.get((key, framework))),
                "review_status": "reviewed"
                if all(m.review_status == "reviewed" for m in group)
                else "draft",
            }
        )
    return out


def requirements_for_framework(
    session: Session, framework: str, controls: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """The framework's requirements (cited references), each with the controls mapped
    to it. A requirement reads ``failing`` if any of its controls fails, ``met`` only
    when every control is effective, and ``attested`` only when every control carries
    a current review."""
    controls = controls if controls is not None else controls_for_framework(session, framework)
    # The catalog cites one clause both bare ("Art. 14") and titled ("Art. 14 — human
    # oversight"); both are the same requirement, shown under its titled form.
    by_ref: dict[str, list[dict[str, Any]]] = {}
    titles: dict[str, str] = {}
    for control in controls:
        for reference in control["references"]:
            clause = reference.split(" — ", 1)[0].strip()
            if len(reference) > len(titles.get(clause, "")):
                titles[clause] = reference
            group = by_ref.setdefault(clause, [])
            if control not in group:
                group.append(control)

    def rank(statuses: list[str]) -> str:
        statuses = [s for s in statuses if s != "not_applicable"] or statuses
        if "failing" in statuses:
            return "failing"
        if statuses and all(s == "effective" for s in statuses):
            return "effective"
        if "degraded" in statuses or "effective" in statuses:
            return "degraded"
        if "not_implemented" in statuses:
            return "not_implemented"
        return statuses[0] if statuses else "not_computed"

    out = []
    for clause in sorted(by_ref, key=_reference_sort_key):
        group = by_ref[clause]
        states = [(c.get("review") or {}).get("state", "none") for c in group]
        out.append(
            {
                "reference": titles[clause],
                "clause": clause,
                "status": rank([c["status"] for c in group]),
                "controls": [
                    {
                        "key": c["key"],
                        "title": c["title"],
                        "status": c["status"],
                        "review": c.get("review"),
                    }
                    for c in group
                ],
                "attested": all(s == "current" for s in states),
                "expired": sum(1 for s in states if s == "expired"),
            }
        )
    return out


def _reference_sort_key(reference: str) -> tuple:
    """`Art. 9` before `Art. 10`; everything else alphabetical."""
    import re

    parts = re.split(r"(\d+)", reference)
    return tuple(int(p) if p.isdigit() else p for p in parts)
