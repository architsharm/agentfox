"""Control catalog loading and framework mapping (NOM-GOV-02).

**Essentially no OSS exists for this.** That
is not an accident — mapping controls to regimes requires product integration and
domain work, not a library. It is also why this is the moat.

Two design decisions worth stating:

* **Content, not code.** Frameworks change (the omnibus delay moved EU AI Act
  high-risk obligations by a year). Mappings live in versioned YAML and ship
  without a release.
* **Review status is enforced, not decorative.** Every mapping loads as ``draft``
  until a qualified reviewer marks it otherwise, drafts are badged in the UI, and
  :mod:`agentfox.apps.report.evidence` ships them in evidence packages only with an
  explicit draft chip. A compliance product that presents unreviewed regulatory
  mappings as evidence is worse than one with no mappings.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Control, FrameworkMapping, Obligation, utcnow
from agentfox.platform.packs import control_files

FRAMEWORK_TITLES = {
    "eu-ai-act": "EU AI Act",
    "nist-ai-rmf": "NIST AI RMF",
    "iso-42001": "ISO/IEC 42001",
    "soc2": "SOC 2",
    "owasp-llm": "OWASP LLM Top 10",
    "owasp-agentic": "OWASP Agentic Threats",
    "mitre-atlas": "MITRE ATLAS",
}


def catalog_paths(directory: Path | None = None) -> list[Path]:
    """The ``controls.yaml`` files the catalog is read from: the compliance packs'.

    `Settings.compliance_dir` (or ``directory``) replaces them with one directory.
    """
    return control_files("controls.yaml", directory)


def catalog_path(directory: Path | None = None) -> Path:
    """The first catalog file; the one a single-pack deployment has."""
    paths = catalog_paths(directory)
    return paths[0] if paths else Path("controls.yaml")


def obligations_paths(directory: Path | None = None) -> list[Path]:
    return control_files("obligations.yaml", directory)


def obligations_path(directory: Path | None = None) -> Path:
    paths = obligations_paths(directory)
    return paths[0] if paths else Path("obligations.yaml")


def merge_catalogs(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Several packs' catalogs as one: controls and gaps concatenated, frameworks merged.

    The first document's version and review status stand for the whole; a framework
    or control key declared twice keeps its first declaration.
    """
    if len(documents) == 1:
        return documents[0]
    merged: dict[str, Any] = {}
    controls: list[Any] = []
    keys: set[Any] = set()
    frameworks: dict[str, Any] = {}
    gaps: dict[str, Any] = {}
    for document in documents:
        for name, value in document.items():
            if name not in ("controls", "frameworks", "gaps"):
                merged.setdefault(name, value)
        for spec in document.get("controls") or []:
            key = spec.get("key") if isinstance(spec, dict) else None
            if key is not None and key in keys:
                continue
            keys.add(key)
            controls.append(spec)
        for name, value in (document.get("frameworks") or {}).items():
            frameworks.setdefault(name, value)
        for name, value in (document.get("gaps") or {}).items():
            gaps.setdefault(name, value)
    merged["frameworks"] = frameworks
    merged["controls"] = controls
    if gaps:
        merged["gaps"] = gaps
    return merged


def load_catalog(directory: Path | None = None) -> dict[str, Any]:
    paths = [path for path in catalog_paths(directory) if path.exists()]
    if not paths:
        return {"version": "unknown", "controls": [], "frameworks": {}, "gaps": {}}
    return merge_catalogs([yaml.safe_load(path.read_text()) or {} for path in paths])


def load_obligations(directory: Path | None = None) -> list[dict[str, Any]]:
    """Every obligation the compliance packs declare, in pack order."""
    out: list[dict[str, Any]] = []
    for path in obligations_paths(directory):
        if path.exists():
            out.extend((yaml.safe_load(path.read_text()) or {}).get("obligations") or [])
    return out


def sync_catalog(session: Session, directory: Path | None = None) -> dict[str, Any]:
    """Load the YAML catalog into the database, preserving review status.

    A previously-reviewed mapping must not silently revert to draft because someone
    edited an unrelated control — but a mapping whose *reference text changed* must,
    because the reviewer approved the old wording, not the new one.
    """
    data = load_catalog(directory)
    version = str(data.get("version", "0.0.0"))
    controls = data.get("controls") or []

    existing_reviews = {
        (m.control_key, m.framework, m.reference): m
        for m in session.scalars(select(FrameworkMapping))
    }

    created = updated = mappings_written = preserved_reviews = 0

    for spec in controls:
        key = spec["key"]
        control = session.scalar(select(Control).where(Control.key == key))
        if control is None:
            control = Control(key=key)
            session.add(control)
            created += 1
        else:
            updated += 1
        control.title = spec.get("title", "")
        control.objective = (spec.get("objective") or "").strip()
        control.family = spec.get("family", key.rsplit("-", 1)[0])
        control.pillar = int(spec.get("pillar", 0))
        control.implemented_by = list(spec.get("implemented_by") or [])
        control.evidence_sources = list(spec.get("evidence_sources") or [])
        control.status_rule_json = dict(spec.get("status_rule") or {})
        control.catalog_version = version
        session.flush()

        seen: set[tuple[str, str, str]] = set()
        for framework, references in (spec.get("mappings") or {}).items():
            for reference in references:
                identity = (key, framework, reference)
                seen.add(identity)
                mapping = existing_reviews.get(identity)
                if mapping is None:
                    mapping = FrameworkMapping(
                        control_key=key,
                        framework=framework,
                        reference=reference,
                        review_status="draft",
                    )
                    session.add(mapping)
                elif mapping.review_status == "reviewed":
                    preserved_reviews += 1
                mappings_written += 1

        # Drop mappings the catalog no longer declares, so a removed citation does
        # not linger as approved evidence.
        for (ckey, framework, reference), mapping in existing_reviews.items():
            if ckey == key and (ckey, framework, reference) not in seen:
                session.delete(mapping)

    session.flush()
    return {
        "version": version,
        "controls_created": created,
        "controls_updated": updated,
        "mappings": mappings_written,
        "reviews_preserved": preserved_reviews,
        "review_status": data.get("review_status", "draft"),
    }


def sync_obligations(session: Session, directory: Path | None = None) -> int:
    if not any(path.exists() for path in obligations_paths(directory)):
        return 0
    count = 0
    for spec in load_obligations(directory):
        reference = spec["reference"]
        framework = spec["framework"]
        obligation = session.scalar(
            select(Obligation).where(
                Obligation.framework == framework, Obligation.reference == reference
            )
        )
        if obligation is None:
            obligation = Obligation(framework=framework, reference=reference)
            session.add(obligation)
        obligation.title = spec.get("title", "")
        obligation.description = (spec.get("description") or "").strip()
        raw_date = spec.get("effective_date")
        obligation.effective_date = (
            dt.datetime.combine(raw_date, dt.time.min, tzinfo=dt.UTC)
            if isinstance(raw_date, dt.date) and not isinstance(raw_date, dt.datetime)
            else raw_date
        )
        obligation.applies_when_json = dict(spec.get("applies_when") or {})
        obligation.status = spec.get("status", "upcoming")
        count += 1
    session.flush()
    return count


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
    from agentfox.capabilities.compliance.reviews import latest_reviews, review_state

    reviews = latest_reviews(session, framework)
    counts = {"current": 0, "expired": 0, "none": 0}
    for key in keys:
        counts[review_state(reviews.get((key, framework)))] += 1
    return counts


def framework_coverage(
    session: Session, framework: str, directory: Path | None = None
) -> dict[str, Any]:
    """Coverage **and declared gaps** — the second half is not optional."""
    from agentfox.capabilities.compliance.status import posture

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
    from agentfox.capabilities.compliance.reviews import latest_reviews, review_json
    from agentfox.capabilities.compliance.status import latest_statuses

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
