"""Coverage by threat — the axis a security engineer actually works along.

This product already slices its data five ways: by agent, by finding, by policy, by
control, by trace. A security engineer asking "how good is our AI security" slices it
a sixth way that nothing here offered — **by threat**. They do not open a tool and
think "show me my detectors". They think "can somebody prompt-inject this", work down
a published list, and expect each entry to answer four questions:

    Is anything watching for it?      detectors
    Is anything stopping it?          policy rules, and enforce vs observe
    Has it actually happened?         detections in the window
    Did we try to break it ourselves? red-team probes and what got through

Every one of those was already recorded and tagged. Detectors stamp `owasp_id` and
`atlas_id` onto each detection. Red-team probes and findings carry the same two
fields. Controls map to `owasp-llm`, `owasp-agentic` and `mitre-atlas`. Policy rules
name the controls they provide evidence for. The whole join existed and nothing
performed it, which is why the inconsistencies survived: detectors write a bare
`LLM01` while the control catalogue writes `LLM01 Prompt Injection`, and `LLM04` was
spelled two different ways in one file. Nobody had ever grouped by the column.

Why this is not part of `compliance/`, which already holds the framework mappings:
a compliance framework is something you attest to, and a threat model is something
you are attacked by. They share a shape — identifiers that controls map onto — and
they are read by different people, at different frequencies, to decide different
things. Filing OWASP as the sixth tab of a compliance page put the security
engineer's primary lens inside the GRC person's screen. The data can stay in one
table; the question does not.

**The ratio is deliberately unflattering.** A threat with nothing mapped to it is a
gap and reports as one, which is the entire reason the catalogue is declared in
`threats.yaml` rather than derived from the mappings — a threat nobody wrote a
control for would otherwise not appear at all, and the one view whose job is to show
gaps would be structurally unable to show the biggest kind.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    Control,
    ControlStatus,
    DetectionFinding,
    FrameworkMapping,
    RedTeamFinding,
    utcnow,
)

log = logging.getLogger(__name__)

#: Intents that mean "this product is supposed to do something about it". Anything
#: else is excluded from the denominator rather than counted as a failure, because a
#: score dragged down by training-data poisoning tells a reader nothing they can act
#: on and teaches them to ignore the number.
SCORED_INTENTS = frozenset({"runtime", "partial"})


def threats_path(directory: Path | None = None) -> Path:
    return (directory or get_settings().compliance_dir) / "threats.yaml"


def load_threats(directory: Path | None = None) -> dict[str, Any]:
    path = threats_path(directory)
    if not path.exists():
        log.warning("no threat catalogue at %s; coverage will be empty", path)
        return {"version": "unknown", "catalogues": {}}
    return yaml.safe_load(path.read_text()) or {}


# ---------------------------------------------------------------------------
# Identifier normalisation
# ---------------------------------------------------------------------------

#: Leading identifier of a mapping reference: "LLM01 Prompt Injection" -> "LLM01",
#: "AML.T0051 LLM Prompt Injection" -> "AML.T0051", "T13 Rogue Agents" -> "T13".
_LEADING_ID = re.compile(r"^\s*(AML\.T\d+|LLM\d+|T\d+)\b", re.I)


def threat_id(reference: str) -> str:
    """The bare identifier from however a reference happens to be written.

    Three conventions are in use across the codebase for the same thing, which is
    itself the evidence that this join had never been made: detectors emit `LLM01`,
    the control catalogue writes `LLM01 Prompt Injection`, and the two spellings of
    `LLM04` ("Data & Model Poisoning", "Data and Model Poisoning") sat in one file
    for as long as nothing compared them. Normalising here rather than rewriting
    every producer keeps this one view from becoming a migration.
    """
    match = _LEADING_ID.match(reference or "")
    return match.group(1).upper() if match else (reference or "").strip().upper()


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


@dataclass
class ThreatCoverage:
    """One published threat, and everything this deployment does about it."""

    catalogue: str
    id: str
    title: str
    coverage_intent: str
    note: str = ""
    controls: list[dict[str, Any]] = field(default_factory=list)
    detectors: list[dict[str, Any]] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)
    detections: int = 0
    redteam_attempts: int = 0
    redteam_breaches: int = 0

    @property
    def scored(self) -> bool:
        return self.coverage_intent in SCORED_INTENTS

    @property
    def enforcing(self) -> bool:
        return any(r["mode"] == "enforce" for r in self.rules)

    @property
    def watching(self) -> bool:
        return bool(self.detectors) or bool(self.rules)

    @property
    def status(self) -> str:
        """One word, in the order a reader's eye should travel.

        `breached` outranks everything: a red-team payload that got through is a
        measured fact about this deployment, and no amount of configuration above it
        changes that. `uncovered` next, because nothing watching is worse than
        something watching and not stopping. `observing` is distinguished from
        `enforcing` because the difference between recording an attack and refusing
        one is the difference the whole product turns on, and a status that blurred
        them would be the single most misleading word on the page.
        """
        if not self.scored:
            return "out_of_scope"
        if self.redteam_breaches:
            return "breached"
        if not self.watching:
            return "uncovered"
        if not self.enforcing:
            return "observing"
        return "enforcing"

    @property
    def detail(self) -> str:
        """The status in words, because a one-word status needs a legend and a
        sentence does not — and the reader of this page is deciding whether to argue
        with it."""
        watching = sum(1 for d in self.detectors if d["available"])
        if not self.scored:
            return self.note or "Not addressable by runtime governance."
        if self.redteam_breaches:
            return (
                f"{self.redteam_breaches} of {self.redteam_attempts} red-team "
                "attempt(s) got through."
            )
        if not self.watching:
            if self.controls:
                return (
                    f"{len(self.controls)} control(s) map to this, but no detector "
                    "watches for it and no live rule acts on it."
                )
            return "Nothing watches for this and nothing acts on it."
        if not self.enforcing:
            parts = []
            if watching:
                parts.append(f"{watching} detector(s) watching")
            if self.rules:
                parts.append(f"{len(self.rules)} rule(s) in observe")
            else:
                parts.append("no rule acts on it")
            return "; ".join(parts).capitalize() + ". Nothing is being stopped."
        enforcing = sum(1 for r in self.rules if r["mode"] == "enforce")
        return f"{enforcing} rule(s) enforcing" + (
            f", {watching} detector(s) watching." if watching else "."
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "catalogue": self.catalogue,
            "id": self.id,
            "title": self.title,
            "coverage_intent": self.coverage_intent,
            "note": self.note,
            "status": self.status,
            "controls": self.controls,
            "detectors": self.detectors,
            "rules": self.rules,
            "detections": self.detections,
            "redteam_attempts": self.redteam_attempts,
            "redteam_breaches": self.redteam_breaches,
        }


def _control_index(session: Session) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """threat id -> the controls mapped to it, plus each control's current status."""
    statuses = {
        row.control_key: row.status
        for row in session.scalars(select(ControlStatus).order_by(ControlStatus.computed_at))
    }
    titles = {c.key: c.title for c in session.scalars(select(Control))}

    by_threat: dict[str, list[dict[str, Any]]] = {}
    mappings = session.scalars(
        select(FrameworkMapping).where(
            FrameworkMapping.framework.in_(("owasp-llm", "owasp-agentic", "mitre-atlas"))
        )
    )
    for mapping in mappings:
        key = threat_id(mapping.reference or "")
        if not key:
            continue
        entry = {
            "key": mapping.control_key,
            "title": titles.get(mapping.control_key, ""),
            "status": statuses.get(mapping.control_key, "not_computed"),
            "review_status": mapping.review_status,
        }
        bucket = by_threat.setdefault(key, [])
        # The catalogue maps a control to a threat once per reference string, and the
        # two spellings of LLM04 mean one control can arrive twice for one threat.
        if not any(e["key"] == entry["key"] for e in bucket):
            bucket.append(entry)
    return by_threat, titles


def _detector_index() -> dict[str, list[dict[str, Any]]]:
    """threat id -> the detectors that stamp it, with whether they are usable.

    Read from the live registry rather than from recorded detections, so a threat
    nothing has triggered yet still shows what is watching for it. A page that only
    listed threats somebody had already been attacked by would be a log, not a
    coverage view.
    """
    from .guardrails import all_detectors

    out: dict[str, list[dict[str, Any]]] = {}
    for key, detector in all_detectors().items():
        for ident in _declared_threats(detector):
            out.setdefault(ident, []).append(
                {
                    "key": key,
                    "available": _safe_available(detector),
                    "unavailable_reason": str(getattr(detector, "unavailable_reason", "") or ""),
                }
            )
    return out


def _declared_threats(detector: Any) -> set[str]:
    """Threat ids a detector says it covers.

    `covers_threats` is the explicit declaration. Falling back to a module-level
    `OWASP` constant picks up the detectors that already had one — several do —
    without a mechanical edit to every file in the package.
    """
    declared = getattr(detector, "covers_threats", None)
    if declared:
        return {threat_id(str(x)) for x in declared}
    module = getattr(type(detector), "__module__", "")
    found: set[str] = set()
    if module:
        import sys

        mod = sys.modules.get(module)
        for attr in ("OWASP", "ATLAS"):
            value = getattr(mod, attr, None)
            if isinstance(value, str) and value:
                found.add(threat_id(value))
    return found


def _safe_available(detector: Any) -> bool:
    try:
        return bool(detector.available())
    except Exception:  # noqa: BLE001 - a broken detector is unavailable, not fatal
        return False


def _rule_index(session: Session, control_titles: dict[str, str]) -> dict[str, list[dict]]:
    """control key -> the live policy rules that provide evidence for it.

    Resolved through `active_layers`, which is the set of *bound* policy versions
    with the binding's own observe/enforce mode attached. A version sitting in the
    store unbound is not protecting anything, and counting it would make this page
    report a threat as enforced when nothing is enforcing it — the one error this
    view must not make, because it is the error that gets somebody breached while
    reading a green screen.
    """
    from .policy.store import active_layers

    out: dict[str, list[dict[str, Any]]] = {}
    for layer in active_layers(session):
        document = layer.document
        for rule in document.rules:
            if not getattr(rule, "enabled", True):
                continue
            for control_key in rule.controls or []:
                out.setdefault(str(control_key), []).append(
                    {
                        "rule_id": rule.id,
                        "policy": document.key,
                        "effect": rule.effect,
                        "mode": document.mode,
                        "level": layer.level,
                        "control": str(control_key),
                        "control_title": control_titles.get(str(control_key), ""),
                    }
                )
    return out


def coverage(
    session: Session, *, window_days: int = 30, directory: Path | None = None
) -> dict[str, Any]:
    """Every published threat, and what this deployment does about it."""
    catalogue_data = load_threats(directory)
    since = utcnow() - dt.timedelta(days=window_days)

    controls_by_threat, control_titles = _control_index(session)
    detectors_by_threat = _detector_index()
    rules_by_control = _rule_index(session, control_titles)

    detections = dict(
        session.execute(
            select(DetectionFinding.owasp_id, func.count())
            .where(DetectionFinding.created_at >= since)
            .group_by(DetectionFinding.owasp_id)
        ).all()
    )
    atlas_detections = dict(
        session.execute(
            select(DetectionFinding.atlas_id, func.count())
            .where(DetectionFinding.created_at >= since)
            .group_by(DetectionFinding.atlas_id)
        ).all()
    )
    detections = {threat_id(str(k)): v for k, v in detections.items() if k} | {
        threat_id(str(k)): v for k, v in atlas_detections.items() if k
    }

    rt_attempts: dict[str, int] = {}
    rt_breaches: dict[str, int] = {}
    for finding in session.scalars(select(RedTeamFinding)):
        for raw in (finding.owasp_id, finding.atlas_id):
            if not raw:
                continue
            key = threat_id(str(raw))
            rt_attempts[key] = rt_attempts.get(key, 0) + 1
            # "Did the payload get through" — the only red-team number that is a
            # fact about this deployment rather than about the probe set.
            if _is_breach(finding):
                rt_breaches[key] = rt_breaches.get(key, 0) + 1

    rows: list[ThreatCoverage] = []
    for catalogue_key, catalogue in (catalogue_data.get("catalogues") or {}).items():
        for entry in catalogue.get("entries") or []:
            ident = threat_id(str(entry.get("id") or ""))
            controls = controls_by_threat.get(ident, [])
            rules: list[dict[str, Any]] = []
            for control in controls:
                rules.extend(rules_by_control.get(control["key"], []))
            rows.append(
                ThreatCoverage(
                    catalogue=catalogue_key,
                    id=ident,
                    title=str(entry.get("title") or ""),
                    coverage_intent=str(entry.get("coverage_intent") or "runtime"),
                    note=str(entry.get("note") or "").strip(),
                    controls=controls,
                    detectors=detectors_by_threat.get(ident, []),
                    rules=rules,
                    detections=detections.get(ident, 0),
                    redteam_attempts=rt_attempts.get(ident, 0),
                    redteam_breaches=rt_breaches.get(ident, 0),
                )
            )

    scored = [r for r in rows if r.scored]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1

    return {
        "version": str(catalogue_data.get("version", "unknown")),
        "window_days": window_days,
        "catalogues": {
            key: {"title": value.get("title", key), "url": value.get("url", "")}
            for key, value in (catalogue_data.get("catalogues") or {}).items()
        },
        "counts": counts,
        "scored": len(scored),
        # Enforcing over scored, and nothing else. Counting `observing` as covered
        # would let a deployment that blocks nothing report full coverage, which is
        # the most expensive wrong number this product could publish.
        "enforcing": sum(1 for r in scored if r.status == "enforcing"),
        "gaps": [r.to_json() for r in scored if r.status in ("uncovered", "breached")],
        "threats": [r.to_json() for r in rows],
    }


def _is_breach(finding: Any) -> bool:
    """Whether this red-team finding means the payload got through.

    `RedTeamFinding.succeeded` is from the attacker's point of view: true means the
    attack worked. Reading it the other way round would turn the most alarming number
    on the page into the most reassuring one.
    """
    return bool(getattr(finding, "succeeded", False))
