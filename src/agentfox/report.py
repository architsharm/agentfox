"""The one-page summary: what is running, what was stopped, what still would not be.

Written for the person who signs off on an agent going to production and will
read one page, not sixteen JSON files. Every number here comes from rows the
product already keeps — decisions, findings, the registry, feedback — and every
sentence is in plain language: no rule ids, no control keys, no internal codes.
Where something is a draft (the framework mappings), the page says so in the
heading rather than in a footnote.

``build_summary`` returns plain data; ``render_markdown`` and ``render_html`` turn
it into the page. ``agentfox report`` prints it, and the evidence package ships it
as ``SUMMARY.md`` / ``SUMMARY.html`` so the zip opens on something a person reads.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .compliance.status import ensure_compliance_computed
from .containment import CAUSES, cause_of, is_detector_rule
from .models import (
    Agent,
    Capability,
    Decision,
    Finding,
    GuardrailFeedback,
    Identity,
    LineageEdge,
    McpServer,
    Tool,
    utcnow,
)

#: Detector-driven refusals get one cause of their own in the counts.
DETECTOR_CAUSE = "detector"
DETECTOR_LABEL = "Harmful content caught (injection, secrets, personal data)"

_UNTRUSTED = ("retrieved", "tool_result", "subagent", "memory")
_IMPACT_ORDER = ("irreversible", "high_impact", "write", "read")
_IMPACT_WORDS = {
    "irreversible": "Irreversible (cannot be undone)",
    "high_impact": "High impact",
    "write": "Changes data",
    "read": "Read-only",
}
_THREAT_STATUS_WORDS = {
    "enforcing": "Blocking",
    "observing": "Watching only — nothing blocked",
    "uncovered": "Gap — nothing watching",
    "breached": "Got through in our own testing",
    "out_of_scope": "Outside what runtime governance can address",
}
#: Codes a reader of this page has never been introduced to. Stripped from any text
#: that reaches it from a rule reason or a finding title.
_CODE = r"(?:NOM-[A-Z]+-\d+|PL-\d+|P\d+(?:-\d+)?|F\d+(?:\.\d+)?)"
_CODE_LIST = re.compile(rf"\s*\(\s*{_CODE}(?:\s*[,/;]\s*{_CODE})*\s*\)")
_INTERNAL_CODE = re.compile(rf"\b{_CODE}\b[,;]?\s?")


def parse_since(value: str | None) -> dt.timedelta:
    """``7d``, ``24h``, ``2w``, ``30m`` — or a bare number of days."""
    text = (value or "7d").strip().lower()
    match = re.fullmatch(r"(\d+)\s*([mhdw]?)", text)
    if not match:
        raise ValueError(f"cannot read {value!r} as a period; try 7d, 24h or 2w")
    amount, unit = int(match.group(1)), match.group(2) or "d"
    return {
        "m": dt.timedelta(minutes=amount),
        "h": dt.timedelta(hours=amount),
        "d": dt.timedelta(days=amount),
        "w": dt.timedelta(weeks=amount),
    }[unit]


def plain(text: str | None) -> str:
    """Remove internal codes from a sentence that came from somewhere else."""
    text = _INTERNAL_CODE.sub("", _CODE_LIST.sub("", text or ""))
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


# ---------------------------------------------------------------------------
# The data
# ---------------------------------------------------------------------------


def build_summary(
    session: Session,
    *,
    agents: list[str] | None = None,
    since: dt.timedelta | None = None,
    period_from: dt.datetime | None = None,
    period_to: dt.datetime | None = None,
    examples: int = 5,
) -> dict[str, Any]:
    """Everything the one-page summary says, as data."""
    period_to = _aware(period_to) or utcnow()
    period_from = _aware(period_from) or (period_to - (since or dt.timedelta(days=7)))
    wanted = [a for a in (agents or []) if a and a != "*"]

    agent_rows = [
        a
        for a in session.scalars(select(Agent).where(Agent.status != "retired"))
        if not wanted or a.slug in wanted
    ]
    agent_ids = {a.id for a in agent_rows}
    slug_by_id = {a.id: a.slug for a in agent_rows}

    decisions = [
        d
        for d in session.scalars(
            select(Decision).where(
                Decision.created_at >= period_from, Decision.created_at <= period_to
            )
        )
        if not wanted or d.agent_id in agent_ids
    ]
    findings = [
        f
        for f in session.scalars(select(Finding).where(Finding.status != "resolved"))
        if (not wanted or f.subject_id in agent_ids)
        and (_aware(f.last_seen_at or f.created_at) or period_to) >= period_from
    ]

    tools_by_agent = _tools_by_agent(session, agent_rows)
    tool_rows = {t.key: t for t in session.scalars(select(Tool))}
    in_scope_tools = (
        {k for keys in tools_by_agent.values() for k in keys} if wanted else set(tool_rows)
    )

    computed = ensure_compliance_computed(session)

    return {
        "generated_at": utcnow().isoformat(timespec="seconds"),
        "period_from": period_from.isoformat(timespec="seconds"),
        "period_to": period_to.isoformat(timespec="seconds"),
        "agents_filter": wanted,
        "inventory": _inventory(session, agent_rows, tool_rows, in_scope_tools),
        "risky_combinations": _risky_combinations(agent_rows, tools_by_agent, tool_rows, decisions),
        "contained": _outcomes(decisions, findings, slug_by_id, applied=True, limit=examples),
        "observe": _outcomes(decisions, findings, slug_by_id, applied=False, limit=examples)
        | {"policies_in_observe": _observe_policies(session)},
        "feedback": _feedback(session, period_from, period_to, agent_ids if wanted else None),
        "coverage": _coverage(session) | {"computed_now": computed},
    }


def _tools_by_agent(session: Session, agents: list[Agent]) -> dict[str, set[str]]:
    import fnmatch

    tool_keys = list(session.scalars(select(Tool.key)))
    out: dict[str, set[str]] = {}
    for agent in agents:
        keys = set(agent.declared_tools or [])
        keys.update(
            session.scalars(
                select(LineageEdge.dst_id).where(
                    LineageEdge.src_type == "agent",
                    LineageEdge.src_id == agent.slug,
                    LineageEdge.dst_type == "tool",
                )
            )
        )
        grants = session.scalars(
            select(Capability.tool_key)
            .join(Identity, Identity.id == Capability.identity_id)
            .where(Identity.agent_id == agent.id)
        )
        for pattern in grants:
            keys.update(k for k in tool_keys if fnmatch.fnmatch(k, pattern))
        out[agent.slug] = keys
    return out


def _inventory(
    session: Session, agents: list[Agent], tools: dict[str, Tool], in_scope: set[str]
) -> dict[str, Any]:
    by_impact: dict[str, list[str]] = {}
    for key in sorted(in_scope):
        impact = tools[key].impact if key in tools else "undeclared"
        by_impact.setdefault(impact, []).append(key)
    ordered = [
        {
            "impact": impact,
            "label": _IMPACT_WORDS.get(impact, "Not yet declared"),
            "count": len(by_impact[impact]),
            "examples": by_impact[impact][:6],
        }
        for impact in (*_IMPACT_ORDER, *sorted(set(by_impact) - set(_IMPACT_ORDER)))
        if impact in by_impact
    ]
    servers = list(session.scalars(select(McpServer).order_by(McpServer.name)))
    return {
        "agents": [
            {
                "slug": a.slug,
                "name": a.name or a.slug,
                "owner": a.owner_email,
                "risk_tier": a.risk_tier,
                "environment": a.environment,
                "registered": a.registered,
                "demo": a.is_seed,
            }
            for a in sorted(agents, key=lambda a: a.slug)
        ],
        "agent_count": len(agents),
        "unowned": sum(1 for a in agents if not a.owner_email),
        "unregistered": sum(1 for a in agents if not a.registered),
        "tools": ordered,
        "tool_count": len(in_scope),
        "mcp_servers": [
            {"name": s.name, "trust": s.trust_level, "pinned": bool(s.pinned_version)}
            for s in servers
        ],
    }


def _risky_combinations(
    agents: list[Agent],
    tools_by_agent: dict[str, set[str]],
    tools: dict[str, Tool],
    decisions: list[Decision],
) -> list[dict[str, Any]]:
    """Agents that both take in content nobody vetted and can act irreversibly.

    The combination, not either half, is the risk: reading a web page is ordinary,
    and so is sending email. An agent that does both can be told by the page to send
    the email. Observed untrusted input counts from recorded decisions; capability
    counts from what the agent is declared, granted or seen to call.
    """
    untrusted_by_agent: dict[str, set[str]] = {}
    for d in decisions:
        taint = d.taint_summary_json or {}
        sources = set((taint.get("arguments") or {}).values()) | {taint.get("max_source")}
        if d.surface in ("tool_result", "retrieved"):
            sources.add("tool_result")
        hits = {s for s in sources if s in _UNTRUSTED}
        if hits and d.agent_id:
            untrusted_by_agent.setdefault(d.agent_id, set()).update(hits)

    out = []
    for agent in agents:
        dangerous = sorted(
            k
            for k in tools_by_agent.get(agent.slug, set())
            if k in tools and tools[k].impact in ("irreversible", "high_impact")
        )
        untrusted = untrusted_by_agent.get(agent.id)
        if not (dangerous and untrusted):
            continue
        out.append(
            {
                "agent": agent.slug,
                "reads": sorted(untrusted),
                "can": dangerous[:5],
                "sentence": (
                    f"{agent.slug} reads content nobody vetted "
                    f"({', '.join(_source_words(s) for s in sorted(untrusted))}) "
                    f"and can {', '.join(dangerous[:3])}"
                    f"{' and more' if len(dangerous) > 3 else ''} — an instruction hidden "
                    "in that content could ask for exactly those actions."
                ),
            }
        )
    return out


def _source_words(source: str) -> str:
    return {
        "retrieved": "documents and web pages",
        "tool_result": "tool output",
        "subagent": "other agents",
        "memory": "stored memory",
    }.get(source, source)


def _outcomes(
    decisions: list[Decision],
    findings: list[Finding],
    slug_by_id: dict[str, str],
    *,
    applied: bool,
    limit: int,
) -> dict[str, Any]:
    """Counts by cause, and the stories behind the biggest ones.

    ``applied=True`` is what was actually stopped or held; ``False`` is what a rule
    in observe mode would have done — recorded, not acted on.
    """
    by_cause: Counter[str] = Counter()
    calls = 0
    for d in decisions:
        causes: set[str] = set()
        for rule in d.rules_fired_json or []:
            if rule.get("effect") not in ("block", "escalate"):
                continue
            rule_applied = rule.get("mode", "enforce") == "enforce" and d.verdict != "allow"
            if rule_applied != applied:
                continue
            if is_detector_rule(rule):
                causes.add(DETECTOR_CAUSE)
            else:
                causes.add(cause_of(str(rule.get("rule_id") or "")))
        if causes:
            calls += 1
            by_cause.update(causes)

    stories = []
    for f in findings:
        ev = f.evidence_json or {}
        if f.type == "containment" and bool(ev.get("applied")) == applied:
            stories.append((f, str(ev.get("cause") or "policy"), plain(f.title)))
        elif f.type == "guardrail_detection":
            would = f.title.lower().startswith("would have")
            if would != applied:
                stories.append((f, DETECTOR_CAUSE, _detection_story(f, slug_by_id)))
    rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    stories.sort(key=lambda p: (rank.get(p[0].severity, 0), p[0].occurrences or 1), reverse=True)
    # One example per cause before a second of any: five stories about the same
    # SQL rule tell a reader less than five different reasons something was stopped.
    first_of_cause: dict[str, int] = {}
    for index, (_f, cause, _s) in enumerate(stories):
        first_of_cause.setdefault(cause, index)
    leaders = set(first_of_cause.values())
    stories = [p for i, p in enumerate(stories) if i in leaders] + [
        p for i, p in enumerate(stories) if i not in leaders
    ]

    return {
        "decisions": calls,
        "by_cause": [
            {
                "cause": cause,
                "label": DETECTOR_LABEL if cause == DETECTOR_CAUSE else CAUSES.get(cause, cause),
                "count": count,
            }
            for cause, count in by_cause.most_common()
        ],
        "examples": [
            {"story": story, "times": f.occurrences or 1, "severity": f.severity}
            for f, _cause, story in stories[:limit]
        ],
    }


_ENTITY_WORDS = {
    "INJECTION": "an injected instruction",
    "SECRET": "a credential",
    "PII": "personal data",
    "SAFETY": "harmful content",
    "SCHEMA": "a malformed answer",
}
_SURFACE_WORDS = {
    "input": "a user's message",
    "output": "a response",
    "tool_args": "a tool call",
    "tool_result": "a tool's output",
    "retrieved": "a retrieved document",
    "reasoning": "the model's reasoning",
    "memory_write": "a memory write",
    "agent_message": "a message between agents",
}


def _detection_story(finding: Finding, slug_by_id: dict[str, str]) -> str:
    ev = finding.evidence_json or {}
    kinds = []
    for det in ev.get("detections") or []:
        family = str(det.get("entity_type") or "").split(".")[0]
        words = _ENTITY_WORDS.get(family)
        if words and words not in kinds:
            kinds.append(words)
    what = " and ".join(kinds) or "something a detector flags"
    where = _SURFACE_WORDS.get(str(ev.get("surface") or ""), "traffic")
    who = slug_by_id.get(finding.subject_id or "", "An agent")
    verdict = str(ev.get("verdict") or "block")
    outcome = {
        "block": "blocked",
        "escalate": "held for review",
        "redact": "redacted",
        "mask": "masked",
        "tokenize": "tokenised",
    }.get(verdict, verdict)
    if finding.title.lower().startswith("would have"):
        outcome = f"would have been {outcome}"
    return f"{who}: {what} in {where} ({outcome})"


def _observe_policies(session: Session) -> list[str]:
    from .policy import active_policies

    seen: dict[str, str] = {}
    for doc, _version, binding in active_policies(session):
        if binding.mode == "observe":
            seen[doc.key] = doc.name or doc.key
    return sorted(seen.values())


def _feedback(
    session: Session, start: dt.datetime, end: dt.datetime, agent_ids: set[str] | None
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in session.scalars(
        select(GuardrailFeedback).where(
            GuardrailFeedback.created_at >= start, GuardrailFeedback.created_at <= end
        )
    ):
        if agent_ids is None or row.agent_id in agent_ids:
            counts[row.label] += 1
    return dict(counts)


def _coverage(session: Session) -> dict[str, Any]:
    from .compliance import posture
    from .threats import coverage

    data = coverage(session)
    title = (data.get("catalogues") or {}).get("owasp-agentic", {}).get("title", "")
    rows = [
        {
            "title": t["title"],
            "status": t["status"],
            "words": _THREAT_STATUS_WORDS.get(t["status"], t["status"]),
        }
        for t in data.get("threats") or []
        if t["catalogue"] == "owasp-agentic"
    ]
    counts = Counter(r["status"] for r in rows)
    overall = posture(session)
    return {
        "catalogue": title or "OWASP Agentic AI threats",
        "threats": rows,
        "counts": dict(counts),
        "controls": overall["controls"],
        "controls_effective": overall["counts"].get("effective", 0),
        "controls_assessed": sum(
            overall["counts"].get(s, 0) for s in ("effective", "degraded", "failing")
        ),
        "controls_without_evidence": overall["counts"].get("not_implemented", 0)
        + overall["counts"].get("not_computed", 0),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

DRAFT_LABEL = "DRAFT — UNVERIFIED"


def _scope_line(data: dict[str, Any]) -> str:
    who = ", ".join(data["agents_filter"]) if data["agents_filter"] else "all agents"
    return f"{who}, {data['period_from'][:10]} to {data['period_to'][:10]}"


def _headline(data: dict[str, Any]) -> str:
    inv = data["inventory"]
    stopped = data["contained"]["decisions"]
    would = data["observe"]["decisions"]
    parts = [
        f"{inv['agent_count']} agent(s) under management",
        f"{stopped} risky action(s) stopped or held for approval",
    ]
    if would:
        parts.append(f"{would} more that observe-mode rules recorded but did not stop")
    if data["risky_combinations"]:
        parts.append(f"{len(data['risky_combinations'])} agent(s) with a risky combination")
    return "; ".join(parts) + "."


def render_markdown(data: dict[str, Any]) -> str:
    inv = data["inventory"]
    lines: list[str] = [
        "# AgentFox summary",
        "",
        f"*{_scope_line(data)}. Generated {data['generated_at']}.*",
        "",
        f"**In short:** {_headline(data)}",
        "",
        "## What is running",
        "",
        f"- **Agents:** {inv['agent_count']}"
        + (f" ({inv['unowned']} with no named owner)" if inv["unowned"] else "")
        + (
            f", {inv['unregistered']} running without being registered"
            if inv["unregistered"]
            else ""
        ),
    ]
    for agent in inv["agents"][:12]:
        owner = agent["owner"] or "no owner"
        tags = [agent["environment"], f"{agent['risk_tier']} risk", owner]
        if agent["demo"]:
            tags.append("demo data")
        lines.append(f"  - {agent['slug']} — {', '.join(tags)}")
    if len(inv["agents"]) > 12:
        lines.append(f"  - and {len(inv['agents']) - 12} more")
    lines.append(f"- **Tools:** {inv['tool_count']}, by what they can do:")
    for row in inv["tools"]:
        lines.append(f"  - {row['label']}: {row['count']} — {', '.join(row['examples'])}")
    if inv["mcp_servers"]:
        unpinned = sum(1 for s in inv["mcp_servers"] if not s["pinned"])
        lines.append(
            f"- **MCP servers:** {len(inv['mcp_servers'])} — "
            + ", ".join(s["name"] for s in inv["mcp_servers"][:8])
            + (f" ({unpinned} not pinned to a reviewed version)" if unpinned else "")
        )
    else:
        lines.append("- **MCP servers:** none recorded")

    if data["risky_combinations"]:
        lines += ["", "## Risky combinations", ""]
        lines += [f"- {row['sentence']}" for row in data["risky_combinations"]]

    lines += ["", "## What was contained", ""]
    lines += _outcome_md(data["contained"], "Nothing was stopped in this period.")

    lines += ["", "## Still in observe mode", ""]
    observe = data["observe"]
    if observe["policies_in_observe"]:
        lines.append(
            "These policies record what they would do without acting on it: "
            + ", ".join(observe["policies_in_observe"])
            + "."
        )
        lines.append("")
    lines += _outcome_md(
        observe, "No observe-mode rule would have stopped anything in this period.", would=True
    )

    lines += ["", "## Feedback on our decisions", ""]
    fb = data["feedback"]
    if fb:
        lines.append(
            f"- Marked wrong (false positive): {fb.get('false_positive', 0)}\n"
            f"- Confirmed right: {fb.get('true_positive', 0)}\n"
            f"- Missed (false negative): {fb.get('false_negative', 0)}"
        )
    else:
        lines.append("No one has reviewed a decision in this period.")

    cov = data["coverage"]
    lines += [
        "",
        f"## Coverage against {cov['catalogue']} — {DRAFT_LABEL}",
        "",
        "> The mapping from these threats to our controls is an engineering draft. It has not "
        "been reviewed by compliance counsel or an auditor and is not a certification.",
        "",
        "| Threat | Status |",
        "| --- | --- |",
    ]
    lines += [f"| {t['title']} | {t['words']} |" for t in cov["threats"]]
    lines += [
        "",
        f"Controls with working evidence: {cov['controls_effective']} of {cov['controls']}; "
        f"{cov['controls_without_evidence']} have no evidence yet"
        + (" (computed just now from recorded activity)." if cov["computed_now"] else "."),
        "",
    ]
    return plain_document("\n".join(lines))


def _outcome_md(block: dict[str, Any], empty: str, *, would: bool = False) -> list[str]:
    if not block["decisions"]:
        return [empty]
    verb = "would have been stopped or held" if would else "stopped or held for approval"
    out = [f"{block['decisions']} action(s) {verb}. By cause:", ""]
    out += [f"- {row['label']}: {row['count']}" for row in block["by_cause"]]
    if block["examples"]:
        out += ["", "Examples:", ""]
        for ex in block["examples"]:
            times = f" — {ex['times']} times" if ex["times"] > 1 else ""
            out.append(f"- {ex['story']}{times}")
    return out


def plain_document(text: str) -> str:
    """Last pass over a rendered page: no internal codes survive, whatever their source."""
    out = "\n".join(_INTERNAL_CODE.sub("", _CODE_LIST.sub("", line)) for line in text.splitlines())
    return out + ("\n" if text.endswith("\n") else "")


_CSS = """
:root{--fg:#1d2433;--muted:#5b6475;--bg:#ffffff;--line:#e3e6ec;--warn:#9a5b00;--ok:#1f7a4a}
@media (prefers-color-scheme: dark){:root{--fg:#e7eaf0;--muted:#a3abba;--bg:#141821;
--line:#2a303c;--warn:#f0b35a;--ok:#5cc58f}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,Segoe UI,sans-serif;
max-width:820px;margin:32px auto;padding:0 16px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;
border-bottom:1px solid var(--line);padding-bottom:4px}
.meta{color:var(--muted);margin:0 0 16px}.lead{font-size:16px}
ul{padding-left:20px}li{margin:2px 0}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
.draft{color:var(--warn);font-weight:600}.note{color:var(--muted);font-size:13px}
"""


def render_html(data: dict[str, Any]) -> str:
    """The same page as HTML: self-contained, no scripts, readable offline."""
    e = html.escape
    inv = data["inventory"]

    def ul(items: list[str]) -> str:
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else ""

    def outcome(block: dict[str, Any], empty: str, would: bool = False) -> str:
        if not block["decisions"]:
            return f"<p>{e(empty)}</p>"
        verb = "would have been stopped or held" if would else "stopped or held for approval"
        body = f"<p>{block['decisions']} action(s) {verb}. By cause:</p>"
        body += ul([f"{e(r['label'])}: {r['count']}" for r in block["by_cause"]])
        if block["examples"]:
            body += "<p>Examples:</p>" + ul(
                [
                    e(x["story"]) + (f" — {x['times']} times" if x["times"] > 1 else "")
                    for x in block["examples"]
                ]
            )
        return body

    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>AgentFox summary</title><style>{_CSS}</style></head><body>",
        "<h1>AgentFox summary</h1>",
        f"<p class='meta'>{e(_scope_line(data))}. Generated {e(data['generated_at'])}.</p>",
        f"<p class='lead'><strong>In short:</strong> {e(_headline(data))}</p>",
        "<h2>What is running</h2>",
    ]
    agents = [
        f"{e(a['slug'])} — {e(a['environment'])}, {e(a['risk_tier'])} risk, "
        f"{e(a['owner'] or 'no owner')}{', demo data' if a['demo'] else ''}"
        for a in inv["agents"][:12]
    ]
    parts.append(
        f"<p><strong>Agents:</strong> {inv['agent_count']}"
        + (f" ({inv['unowned']} with no named owner)" if inv["unowned"] else "")
        + "</p>"
        + ul(agents)
    )
    parts.append(
        f"<p><strong>Tools:</strong> {inv['tool_count']}, by what they can do:</p>"
        + ul(
            [f"{e(r['label'])}: {r['count']} — {e(', '.join(r['examples']))}" for r in inv["tools"]]
        )
    )
    servers = inv["mcp_servers"]
    parts.append(
        "<p><strong>MCP servers:</strong> "
        + (e(", ".join(s["name"] for s in servers[:8])) if servers else "none recorded")
        + "</p>"
    )
    if data["risky_combinations"]:
        parts.append("<h2>Risky combinations</h2>")
        parts.append(ul([e(r["sentence"]) for r in data["risky_combinations"]]))
    parts.append("<h2>What was contained</h2>")
    parts.append(outcome(data["contained"], "Nothing was stopped in this period."))
    parts.append("<h2>Still in observe mode</h2>")
    observe = data["observe"]
    if observe["policies_in_observe"]:
        parts.append(
            "<p>These policies record what they would do without acting on it: "
            + e(", ".join(observe["policies_in_observe"]))
            + ".</p>"
        )
    parts.append(outcome(observe, "No observe-mode rule would have stopped anything.", would=True))
    parts.append("<h2>Feedback on our decisions</h2>")
    fb = data["feedback"]
    parts.append(
        ul(
            [
                f"Marked wrong (false positive): {fb.get('false_positive', 0)}",
                f"Confirmed right: {fb.get('true_positive', 0)}",
                f"Missed (false negative): {fb.get('false_negative', 0)}",
            ]
        )
        if fb
        else "<p>No one has reviewed a decision in this period.</p>"
    )
    cov = data["coverage"]
    parts.append(
        f"<h2>Coverage against {e(cov['catalogue'])} — "
        f"<span class='draft'>{DRAFT_LABEL}</span></h2>"
        "<p class='note'>The mapping from these threats to our controls is an engineering "
        "draft. It has not been reviewed by compliance counsel or an auditor and is not a "
        "certification.</p><table><tr><th>Threat</th><th>Status</th></tr>"
        + "".join(
            f"<tr><td>{e(t['title'])}</td><td>{e(t['words'])}</td></tr>" for t in cov["threats"]
        )
        + "</table>"
        f"<p class='note'>Controls with working evidence: {cov['controls_effective']} of "
        f"{cov['controls']}; {cov['controls_without_evidence']} have no evidence yet"
        + (" (computed just now from recorded activity)." if cov["computed_now"] else ".")
        + "</p>"
    )
    parts.append("</body></html>")
    return plain_document("\n".join(parts))


__all__ = [
    "DRAFT_LABEL",
    "build_summary",
    "ensure_compliance_computed",
    "parse_since",
    "plain",
    "render_html",
    "render_markdown",
]
