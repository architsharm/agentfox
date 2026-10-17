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
  enterprise evidence packages (`agentfox_ee.evidence`) ship them only with an
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

from agentfox.core.models import Control, FrameworkMapping, Obligation
from agentfox.platform.packs import control_files


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


def catalog_behind(session: Session) -> bool:
    """Whether this tenant's stored catalog differs from the one this build ships:
    a control added or removed, a different catalog version, or a different number of
    framework mappings. Cheap: one query per table, no YAML written."""
    from sqlalchemy import func

    data = load_catalog()
    shipped = data.get("controls") or []
    keys = {c["key"] for c in shipped}
    stored = set(session.scalars(select(Control.key)))
    if keys != stored:
        return True
    version = str(data.get("version", "0.0.0"))
    if session.scalar(select(Control.id).where(Control.catalog_version != version).limit(1)):
        return True
    mappings = sum(len(refs) for c in shipped for refs in (c.get("mappings") or {}).values())
    return session.scalar(select(func.count()).select_from(FrameworkMapping)) != mappings


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


def ensure_catalog_current(session: Session) -> bool:
    """Bring this workspace's stored catalog up to the one this build ships, if behind.

    Several requests can find it behind at once (a page loads its controls, frameworks
    and risk register in parallel), and two inserting the same control is a unique-key
    conflict. The sync runs in a savepoint; losing that race means another request is
    loading the same catalog, so the conflict is rolled back and not an error.
    Returns whether this call synced.
    """
    from sqlalchemy.exc import IntegrityError

    if not catalog_behind(session):
        return False
    try:
        with session.begin_nested():
            sync_catalog(session)
    except IntegrityError:
        return False
    return True
