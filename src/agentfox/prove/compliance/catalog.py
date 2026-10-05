"""Control catalog loading and framework mapping (P6-2, P6-8, NOM-GOV-02).

Appendix A.5's finding for this pillar is stark: **essentially no OSS exists.** That
is not an accident — mapping controls to regimes requires product integration and
domain work, not a library. It is also why this is the moat.

Two design decisions worth stating:

* **Content, not code.** Frameworks change (the omnibus delay moved EU AI Act
  high-risk obligations by a year while this was being written). Mappings live in
  versioned YAML and ship without a release (PRD R6).
* **Review status is enforced, not decorative.** Every mapping loads as ``draft``
  until a qualified reviewer marks it otherwise, drafts are badged in the UI, and
  :mod:`agentfox.prove.audit.evidence` excludes them from evidence packages entirely
  (Appendix B §B.6). A compliance product that presents unreviewed regulatory
  mappings as evidence is worse than one with no mappings.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
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


def catalog_path(directory: Path | None = None) -> Path:
    return (directory or get_settings().compliance_dir) / "controls.yaml"


def obligations_path(directory: Path | None = None) -> Path:
    return (directory or get_settings().compliance_dir) / "obligations.yaml"


def load_catalog(directory: Path | None = None) -> dict[str, Any]:
    path = catalog_path(directory)
    if not path.exists():
        return {"version": "unknown", "controls": [], "frameworks": {}, "gaps": {}}
    return yaml.safe_load(path.read_text()) or {}


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
    path = obligations_path(directory)
    if not path.exists():
        return 0
    data = yaml.safe_load(path.read_text()) or {}
    count = 0
    for spec in data.get("obligations") or []:
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
    """Mark mapping(s) reviewed. Gate step 3 of Appendix B §B.6."""
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


def framework_coverage(
    session: Session, framework: str, directory: Path | None = None
) -> dict[str, Any]:
    """Coverage **and declared gaps** — the second half is not optional."""
    data = load_catalog(directory)
    total_controls = session.scalars(select(Control)).all()
    mappings = list(
        session.scalars(select(FrameworkMapping).where(FrameworkMapping.framework == framework))
    )
    mapped_keys = {m.control_key for m in mappings}
    reviewed = [m for m in mappings if m.review_status == "reviewed"]

    return {
        "framework": framework,
        "title": FRAMEWORK_TITLES.get(framework, framework),
        "description": (data.get("frameworks") or {}).get(framework, ""),
        "controls_total": len(total_controls),
        "controls_mapped": len(mapped_keys),
        "references": sorted({m.reference for m in mappings}),
        "mappings_total": len(mappings),
        "mappings_reviewed": len(reviewed),
        "mappings_draft": len(mappings) - len(reviewed),
        "review_status": "reviewed" if mappings and len(reviewed) == len(mappings) else "draft",
        # Rendered next to every coverage claim in the product.
        "declared_gaps": (data.get("gaps") or {}).get(framework, []),
        "caveat": (
            "Mappings are informed engineering drafts produced from the framework "
            "texts. They are not legal advice and have not been reviewed by "
            "compliance counsel or a certification body. Draft mappings do ship in "
            "evidence packages, labelled DRAFT — UNVERIFIED / NOT LEGAL ADVICE."
        ),
    }


def all_frameworks(session: Session, directory: Path | None = None) -> list[dict[str, Any]]:
    data = load_catalog(directory)
    keys = list((data.get("frameworks") or FRAMEWORK_TITLES).keys())
    return [framework_coverage(session, key, directory) for key in keys]


def controls_for_framework(session: Session, framework: str) -> list[dict[str, Any]]:
    mappings = list(
        session.scalars(select(FrameworkMapping).where(FrameworkMapping.framework == framework))
    )
    by_control: dict[str, list[FrameworkMapping]] = {}
    for mapping in mappings:
        by_control.setdefault(mapping.control_key, []).append(mapping)

    out: list[dict[str, Any]] = []
    for key, group in sorted(by_control.items()):
        control = session.scalar(select(Control).where(Control.key == key))
        if control is None:
            continue
        out.append(
            {
                "key": key,
                "title": control.title,
                "pillar": control.pillar,
                "implemented_by": control.implemented_by,
                "references": [m.reference for m in group],
                "review_status": "reviewed"
                if all(m.review_status == "reviewed" for m in group)
                else "draft",
            }
        )
    return out
