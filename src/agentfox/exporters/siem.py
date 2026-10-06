"""SIEM / OTel export (NOM-AUD-04).

Principle: **never require the customer to adopt our storage as their system of
record.** A security team already has a SOC, already has correlation rules, and
already has an on-call rotation wired to it. A governance tool that demands they
watch a second console is a tool they will watch for two weeks.

Four formats, deliberately: OTLP for modern pipelines, JSON Lines for anything that
tails a file, and CEF/LEEF because ArcSight and QRadar are still what large
regulated buyers run — which is exactly the Tier-C buyer this pillar exists for.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Decision, DetectionFinding, Finding, Trace

VENDOR = "AgentFox"
PRODUCT = "ControlPlane"
VERSION = "0.1.0"

#: Verdict -> CEF severity (0-10). A block is an event a SOC should see; an
#: observe-mode "would have blocked" is informational until enforcement is on.
_SEVERITY = {"block": 8, "escalate": 6, "redact": 4, "mask": 4, "tokenize": 3, "allow": 1}

_CEF_ESCAPE = str.maketrans({"\\": "\\\\", "|": "\\|", "=": "\\=", "\n": " ", "\r": " "})


def _cef_escape(value: Any) -> str:
    return str(value).translate(_CEF_ESCAPE)


def decision_event(session: Session, decision: Decision) -> dict[str, Any]:
    """Canonical event shape. All formats are projections of this."""
    trace = session.get(Trace, decision.trace_id) if decision.trace_id else None
    rules = decision.rules_fired_json or []
    entities = (
        sorted(
            {
                f.entity_type
                for f in session.scalars(
                    select(DetectionFinding).where(DetectionFinding.trace_id == decision.trace_id)
                )
            }
        )
        if decision.trace_id
        else []
    )

    return {
        "event_type": "agent.decision",
        "event_id": decision.id,
        "timestamp": _iso(decision.created_at),
        "agent": trace.agent_slug if trace else None,
        "environment": trace.environment if trace else None,
        "trace_id": decision.trace_id,
        "surface": decision.surface,
        "tool": decision.tool_key,
        "verdict": decision.verdict,
        "mode": decision.mode,
        "policy_version_id": decision.policy_version_id,
        "rules_fired": [r.get("rule_id") for r in rules],
        "reasons": [r.get("reason") for r in rules][:5],
        "controls": sorted({c for r in rules for c in (r.get("controls") or [])}),
        "entities": entities,
        "taint": (decision.taint_summary_json or {}).get("max_source"),
        "latency_ms": decision.latency_ms,
        "severity": _SEVERITY.get(decision.verdict, 1),
    }


def finding_event(finding: Finding) -> dict[str, Any]:
    return {
        "event_type": f"governance.finding.{finding.type}",
        "event_id": finding.id,
        "timestamp": _iso(finding.created_at),
        "title": finding.title,
        "severity_label": finding.severity,
        "severity": {"critical": 10, "high": 8, "medium": 5, "low": 2}.get(finding.severity, 5),
        "subject_type": finding.subject_type,
        "subject_id": finding.subject_id,
        "status": finding.status,
        "controls": finding.control_keys,
        "evidence": finding.evidence_json,
    }


# --- Formats ---------------------------------------------------------------


def to_jsonl(events: Iterable[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e, default=str) for e in events)


def to_cef(events: Iterable[dict[str, Any]]) -> str:
    """ArcSight Common Event Format."""
    lines = []
    for e in events:
        name = _cef_escape(e.get("event_type", "event"))
        signature = _cef_escape(e.get("verdict") or e.get("severity_label") or "event")
        extensions = {
            "rt": e.get("timestamp"),
            "externalId": e.get("event_id"),
            "act": e.get("verdict") or e.get("status"),
            "duser": e.get("agent"),
            "deviceCustomString1": e.get("tool"),
            "deviceCustomString1Label": "tool",
            "deviceCustomString2": ",".join(e.get("rules_fired") or []),
            "deviceCustomString2Label": "rules",
            "deviceCustomString3": ",".join(e.get("controls") or []),
            "deviceCustomString3Label": "controls",
            "deviceCustomString4": ",".join(e.get("entities") or []),
            "deviceCustomString4Label": "entities",
            "cs5": e.get("trace_id"),
            "cs5Label": "traceId",
            "msg": "; ".join(str(r) for r in (e.get("reasons") or []) if r),
        }
        ext = " ".join(
            f"{k}={_cef_escape(v)}" for k, v in extensions.items() if v not in (None, "")
        )
        lines.append(
            f"CEF:0|{VENDOR}|{PRODUCT}|{VERSION}|{name}|{signature}|{e.get('severity', 1)}|{ext}"
        )
    return "\n".join(lines)


def to_leef(events: Iterable[dict[str, Any]]) -> str:
    """IBM QRadar Log Event Extended Format."""
    lines = []
    for e in events:
        attrs = {
            "devTime": e.get("timestamp"),
            "cat": e.get("event_type"),
            "sev": e.get("severity"),
            "usrName": e.get("agent"),
            "traceId": e.get("trace_id"),
            "tool": e.get("tool"),
            "verdict": e.get("verdict"),
            "rules": ",".join(e.get("rules_fired") or []),
            "controls": ",".join(e.get("controls") or []),
            "entities": ",".join(e.get("entities") or []),
        }
        body = "\t".join(f"{k}={v}" for k, v in attrs.items() if v not in (None, ""))
        lines.append(f"LEEF:2.0|{VENDOR}|{PRODUCT}|{VERSION}|{e.get('event_type')}|\t{body}")
    return "\n".join(lines)


def to_otlp(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """OTLP/JSON log records — the default for anything modern."""
    records = []
    for e in events:
        ts = e.get("timestamp")
        nanos = 0
        if ts:
            nanos = int(dt.datetime.fromisoformat(str(ts)).timestamp() * 1_000_000_000)
        records.append(
            {
                "timeUnixNano": str(nanos),
                "severityNumber": min(int(e.get("severity", 1)) * 2, 24),
                "severityText": str(e.get("verdict") or e.get("severity_label") or "INFO").upper(),
                "body": {"stringValue": e.get("event_type", "event")},
                "attributes": [
                    {
                        "key": k,
                        "value": {
                            "stringValue": json.dumps(v, default=str)
                            if isinstance(v, (list, dict))
                            else str(v)
                        },
                    }
                    for k, v in e.items()
                    if v is not None and k not in ("event_type", "severity")
                ],
            }
        )
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "agentfox"}},
                        {"key": "service.version", "value": {"stringValue": VERSION}},
                    ]
                },
                "scopeLogs": [{"scope": {"name": "agentfox.governance"}, "logRecords": records}],
            }
        ]
    }


def export(
    session: Session,
    fmt: str = "jsonl",
    *,
    since: dt.datetime | None = None,
    limit: int = 1000,
    include_findings: bool = True,
) -> str:
    query = select(Decision).order_by(Decision.created_at.desc()).limit(limit)
    if since:
        query = query.where(Decision.created_at >= since)
    events = [decision_event(session, d) for d in session.scalars(query)]

    if include_findings:
        fquery = select(Finding).order_by(Finding.created_at.desc()).limit(limit)
        if since:
            fquery = fquery.where(Finding.created_at >= since)
        events.extend(finding_event(f) for f in session.scalars(fquery))

    events.sort(key=lambda e: str(e.get("timestamp") or ""))

    if fmt == "cef":
        return to_cef(events)
    if fmt == "leef":
        return to_leef(events)
    if fmt == "otlp":
        return json.dumps(to_otlp(events), indent=2, default=str)
    return to_jsonl(events)


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.isoformat()
