"""`agentfox init`'s map of a repository: who talks to it, the agents, their tools, and
the systems those tools touch.

A thin adapter over discovery. The repository is read by the same static scanner as
`agentfox scan` and a connected GitHub repository
(:func:`agentfox.capabilities.discovery.repo.scan`, whose
:mod:`~agentfox.capabilities.discovery.agents` finds each agent, its tools and model,
and who hands work to whom), and every tool is classified by the same two classifiers
the rest of the product uses: what it can reach
(:func:`agentfox.capabilities.discovery.exposure.classify_tool`) and what it can change
(:func:`agentfox.platform.registry.impact.infer_impact`). This module only turns that
into the onboarding's ``structure`` (the dashboard's ``Structure`` type) and its plain
words: a risk label per tool, the system it touches, a sentence of what it does, who
the agents serve.

Static and local: it never imports or runs the user's code. What leaves the machine is
names and shapes only — tool names, one line of each docstring, argument names, a model
id — never data or prompts.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from agentfox.capabilities.discovery.agents import RECOGNISED, AgentSpec
from agentfox.capabilities.discovery.exposure import EXFIL, PRIVATE, Capabilities, classify_tool
from agentfox.capabilities.discovery.repo import ScanReport, scan
from agentfox.platform.registry.impact import handoff, infer_impact, tokens
from agentfox.platform.registry.projects import systems_of

__all__ = [
    "RECOGNISED",
    "classify",
    "map_repository",
    "plain_sentence",
    "structure_from_scan",
    "system_for",
]


# --- What a tool can do, from discovery's classifiers -------------------------


def classify(name: str, doc: str = "") -> tuple[str, str]:
    """(risk, reason) for one tool: ``high`` | ``outside`` | ``read_only``.

    Read from :func:`classify_tool` (can it send data out, move money, delete?) and
    :func:`infer_impact` (does it change anything?). Nothing here decides on its own:
    it only says the classifiers' answer in the onboarding's three words.
    """
    caps = classify_tool(name, doc)
    impact = infer_impact(name, {"description": doc}, cautious=True)
    return _risk(name, caps, impact)


def _risk(name: str, caps: Capabilities, impact: str) -> tuple[str, str]:
    toks = tokens(name)
    if EXFIL in caps.flags:
        if caps.action == "move money":
            return "high", "moves money"
        if caps.action == "delete data":
            return "high", "deletes data"
        if caps.action == "run commands on this machine":
            return "high", "runs commands"
        if caps.action == "send {data} out":
            return "outside", "talks to the outside"
        return "high", "acts irreversibly"
    if handoff(toks):
        return "outside", "hands the conversation to a person"
    # A read of personal data in bulk is how a customer table leaves.
    if PRIVATE in caps.flags and set(toks) & {"export", "dump", "bulk"}:
        return "high", "exports personal data"
    if impact in ("irreversible", "high_impact"):
        return "high", "acts irreversibly"
    if impact == "write":
        return "high", "changes data"
    return "read_only", "only reads"


#: (words in the tool's name, system, kind) — first match wins. Whole words only:
#: "ship" is not in ``get_membership_status``, "order" is not in ``border``.
_SYSTEMS: tuple[tuple[frozenset[str], str, str], ...] = (
    (frozenset({"email", "emails", "mail", "smtp", "sendgrid", "inbox"}), "Email", "email"),
    (
        frozenset({"escalate", "escalation", "ticket", "tickets", "helpdesk", "zendesk"}),
        "Helpdesk",
        "helpdesk",
    ),
    (
        frozenset({"order", "orders", "cart", "product", "products", "inventory", "catalog"}),
        "Orders",
        "database",
    ),
    (
        frozenset({"ship", "shipping", "shipment", "shipments", "carrier", "delivery", "parcel"}),
        "Shipping carrier",
        "external",
    ),
    (
        frozenset(
            {
                "customer",
                "customers",
                "crm",
                "contact",
                "contacts",
                "account",
                "accounts",
                "profile",
                "profiles",
                "user",
                "users",
                "member",
                "membership",
            }
        ),  # fmt: skip
        "Customer records",
        "crm",
    ),
    (
        frozenset({"sql", "database", "db", "postgres", "mysql", "table", "tables"}),
        "Database",
        "database",
    ),
    (
        frozenset({"slack", "webhook", "http", "https", "api", "url", "web"}),
        "External API",
        "external",
    ),
)


def system_for(name: str, doc: str, risk: str, caps: Capabilities | None = None) -> tuple[str, str]:
    """(system, kind) a tool touches: Payments for a tool that moves money, a
    helpdesk for one that hands the chat to a person, else the first system its name
    (then its description) names."""
    caps = caps if caps is not None else classify_tool(name, doc)
    if caps.action == "move money":
        return "Payments", "payments"
    toks = tokens(name)
    if handoff(toks):
        return "Helpdesk", "helpdesk"
    for words in (set(toks), set(tokens(doc))):
        for keys, sys_name, kind in _SYSTEMS:
            if words & keys:
                return sys_name, kind
    return "Internal service", "external"


def plain_sentence(doc: str, name: str) -> str:
    first = " ".join((doc or "").strip().split())
    if not first:
        return f"Runs {name}."
    sentences = re.split(r"(?<=[.!?])\s", first)
    return sentences[0] if sentences[0].endswith((".", "!", "?")) else sentences[0] + "."


# --- Who the agents serve, and the project's name ----------------------------------


def _project_name(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            name = tomllib.loads(pyproject.read_text()).get("project", {}).get("name")
            if name:
                return str(name)
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return root.resolve().name


def _who_talks(root: Path, prompts: str) -> tuple[str, str]:
    text = prompts.lower()
    label = (
        "Customers"
        if re.search(r"customer|buyer|shopper|client|passenger|traveler|traveller", text)
        else "Employees"
        if re.search(r"employee|staff|it support|helpdesk", text)
        else "Users"
    )
    for entry, how in (
        ("chat.py", "chat"),
        ("app.py", "app"),
        ("server.py", "API"),
        ("main.py", "app"),
        ("streamlit_app.py", "web app"),
        ("bot.py", "bot"),
    ):
        if (root / entry).is_file():
            return label, f"{how}, {entry}"
    return label, "chat"


# --- The map ------------------------------------------------------------------------


def map_repository(root: str | Path = ".") -> dict[str, Any]:
    """Scan ``root`` and return the onboarding map.

    ``{"structure": Structure, "agents": [runner refs], "project", "root", "read",
    "unreadable", "unassigned_tools", "skipped", "frameworks", "edges"}``: the map the
    dashboard draws, how a local runner reaches each agent, and what the CLI says about
    what the scan could not read.
    """
    root = Path(root).resolve()
    report = scan(root, include_config=False)
    return structure_from_scan(report, root)


def structure_from_scan(report: ScanReport, root: Path) -> dict[str, Any]:
    """The onboarding map of one discovery scan."""
    project = _project_name(root)
    # Each system's entry agent first, then what it hands work to: the order the
    # dashboard's projects use (`platform/registry/projects.systems_of`), so the first
    # agent is the one a test talks to.
    systems = systems_of(
        [a.key for a in report.agents],
        [(e.parent, e.child, e.relation) for e in report.agent_edges],
    )
    systems.sort(key=lambda s: -len(s["members"]))  # the biggest system first
    order = list(dict.fromkeys(m["slug"] for s in systems for m in s["members"]))
    by_key = {a.key: a for a in report.agents}
    specs: list[AgentSpec] = [by_key[k] for k in order]
    roots = {s["root"] for s in systems}
    ids = {a.key: f"ag-{i + 1}" for i, a in enumerate(specs)}
    children: dict[str, list[tuple[str, str]]] = {}
    for edge in report.agent_edges:
        children.setdefault(edge.parent, []).append((edge.child, edge.relation))

    who, detail = _who_talks(root, " ".join(a.instructions or "" for a in specs))
    structure: dict[str, Any] = {
        "sources": [{"id": "src-1", "label": who, "detail": detail}] if specs else [],
        "agents": [],
        "tools": [],
        "systems": [],
    }
    systems: dict[str, dict[str, str]] = {}
    for spec in specs:
        agent_id = ids[spec.key]
        # One agent the code never named takes the project's name.
        name = project if len(specs) == 1 and not spec.named else spec.name
        kids = [(ids[c], r) for c, r in children.get(spec.key, []) if c in ids]
        structure["agents"].append(
            {
                "id": agent_id,
                "key": spec.key,
                "name": name,
                "model": spec.model or "unknown model",
                "models": [spec.model] if spec.model else [],
                "framework": spec.framework,
                "kind": spec.kind,
                # The entry point of its system: nothing else hands it work.
                "root": spec.key in roots,
                "file": spec.file,
                "line": spec.line,
                "sourceIds": ["src-1"],
                # Every relation discovery reads is a hand-off of work; how is in `handoffs`.
                "handsOffTo": [c for c, _ in kids],
                "handoffs": [{"agentId": c, "relation": r} for c, r in kids],
            }
        )
        details = {d["name"]: d for d in spec.tool_details}
        for tname in spec.tools:
            d = details.get(tname, {})
            doc = str(d.get("description") or "")
            caps = classify_tool(tname, doc)
            impact = infer_impact(tname, {"description": doc}, cautious=True)
            risk, why = _risk(tname, caps, impact)
            sys_name, kind = system_for(tname, doc, risk, caps)
            sys_id = "sys-" + re.sub(r"[^a-z0-9]+", "-", sys_name.lower()).strip("-")
            systems.setdefault(sys_id, {"id": sys_id, "name": sys_name, "kind": kind})
            structure["tools"].append(
                {
                    "id": f"t-{agent_id}-{tname}",
                    "name": tname,
                    "agentId": agent_id,
                    "risk": risk,
                    "why": why,
                    "impact": impact,
                    "capabilities": caps.ordered(),
                    "whatItDoes": plain_sentence(doc, tname),
                    "systemId": sys_id,
                    "args": list(d.get("args") or []),
                }
            )
    structure["systems"] = list(systems.values())
    runners = [
        {
            "agentId": ids[a.key],
            "module": a.module,
            "attr": a.attr,
            "kind": a.attr_kind,
            "framework": a.framework,
        }
        for a in specs
    ]
    return {
        "structure": structure,
        "agents": runners,
        "project": project,
        "root": str(root),
        # What the CLI tells you about what it may have missed.
        "read": report.code_files_scanned or 0,
        "unreadable": [e.split(":", 1)[0] for e in report.errors],
        "errors": list(report.errors),
        "unassigned_tools": list(report.unassigned_tools),
        "skipped": dict(report.skipped_suffixes),
        "skipped_summary": report.skipped_summary(),
        "frameworks": list(report.frameworks),
        "edges": [e.to_json() for e in report.agent_edges],
    }
