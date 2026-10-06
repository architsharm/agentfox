"""What a monitor remembers between runs, and what counts as a change worth a finding.

Pure functions, no database: a snapshot is a JSON-able dict built from a scan, and a
diff of two snapshots is a list of :class:`Condition` plus the set of conditions that
still hold. `agentfox.monitoring.service` turns the first into findings and uses the
second to close findings whose condition has cleared.

Keys are what make a diff meaningful. A rescan moves line numbers every time someone
edits the file above a call, so no key here contains a line number: a model call is
identified by its file, provider and call text, a tool by its file and name, an
operation by its method and path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agentfox.capabilities.discovery.repo import ScanReport

#: Finding types a monitor raises and closes. `service.reconcile` only ever closes
#: findings of these types (plus whatever a registered kind declares), so a monitor
#: can never close a finding some other producer owns.
LETHAL_TRIFECTA = "monitor_lethal_trifecta"
UNGOVERNED_MODEL_CALL = "monitor_ungoverned_model_call"
GOVERNANCE_REMOVED = "monitor_governance_removed"
NEW_TOOL = "monitor_new_tool"
NEW_MCP_SERVER = "monitor_new_mcp_server"
API_DESTRUCTIVE_ENDPOINT = "monitor_api_destructive_endpoint"
API_NEW_ENDPOINT = "monitor_api_new_endpoint"
MONITOR_FAILING = "monitor_failing"

REPO_TYPES = (LETHAL_TRIFECTA, UNGOVERNED_MODEL_CALL, GOVERNANCE_REMOVED, NEW_TOOL, NEW_MCP_SERVER)
API_TYPES = (API_DESTRUCTIVE_ENDPOINT, API_NEW_ENDPOINT)


@dataclass(frozen=True)
class Condition:
    """One problem a run found. ``(type, key)`` is its identity within the monitor."""

    type: str
    key: str
    title: str
    severity: str = "medium"
    evidence: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
    control_keys: tuple[str, ...] = ("NOM-DSC-05",)


@dataclass
class Diff:
    """New conditions (raise these) and every condition that still holds (keep these
    open; close any other open finding of ``managed_types``)."""

    new: list[Condition] = field(default_factory=list)
    holding: set[tuple[str, str]] = field(default_factory=set)
    managed_types: tuple[str, ...] = ()
    changes: dict[str, Any] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return any(self.changes.get(k) for k in ("added", "removed")) or bool(self.new)


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


def _site_key(kind: str, file: str, ident: str) -> str:
    return f"{kind}:{file}:{ident}"


def repo_snapshot(report: ScanReport) -> dict[str, Any]:
    """The parts of a repository scan the next scan is compared with."""
    trifectas: dict[str, Any] = {}
    governable: dict[str, Any] = {}
    tools: dict[str, Any] = {}
    servers: dict[str, Any] = {}
    for site in report.sites:
        if site.kind == "lethal_trifecta":
            key = _site_key("trifecta", site.file, site.provider or "code")
            trifectas[key] = {
                "file": site.file,
                "line": site.line,
                "detail": site.detail,
                "evidence": {k: v for k, v in site.evidence.items() if k != "fix"},
                "fix": site.evidence.get("fix"),
            }
        elif site.kind in ("model_call", "agent_definition"):
            key = _site_key(site.kind, site.file, f"{site.provider or ''}:{site.detail}")
            entry = governable.setdefault(
                key,
                {
                    "kind": site.kind,
                    "file": site.file,
                    "line": site.line,
                    "detail": site.detail,
                    "provider": site.provider,
                    "governed": True,
                },
            )
            # Several identical calls in one file share a key; one ungoverned copy is
            # enough to call the key ungoverned.
            entry["governed"] = entry["governed"] and bool(site.governed)
        elif site.kind == "tool":
            key = _site_key("tool", site.file, site.name or site.detail)
            tools[key] = {
                "file": site.file,
                "line": site.line,
                "name": site.name or site.detail,
                "capabilities": list(site.capabilities),
            }
        elif site.kind == "mcp_server":
            key = _site_key("mcp", site.file, site.name or site.detail)
            servers[key] = {
                "file": site.file,
                "name": site.name or site.detail,
                "detail": site.detail,
                "capabilities": list(site.capabilities),
            }
    return {
        "type": "repo",
        "files_scanned": report.files_scanned,
        "code_files_scanned": report.code_files_scanned,
        "inconclusive": report.inconclusive,
        "frameworks": list(report.frameworks),
        "counts": report.by_kind(),
        "trifectas": trifectas,
        "governable": governable,
        "tools": tools,
        "mcp_servers": servers,
    }


def _where(entry: dict[str, Any]) -> str:
    line = entry.get("line")
    return f"{entry.get('file')}:{line}" if line else str(entry.get("file"))


def diff_repo(previous: dict[str, Any], current: dict[str, Any], *, label: str) -> Diff:
    """Compare two `repo_snapshot` results. ``label`` names the repository in titles."""
    diff = Diff(managed_types=REPO_TYPES)
    prev_tri = previous.get("trifectas") or {}
    cur_tri = current.get("trifectas") or {}
    prev_gov = previous.get("governable") or {}
    cur_gov = current.get("governable") or {}
    prev_tools = previous.get("tools") or {}
    cur_tools = current.get("tools") or {}
    prev_mcp = previous.get("mcp_servers") or {}
    cur_mcp = current.get("mcp_servers") or {}

    for key, entry in cur_tri.items():
        diff.holding.add((LETHAL_TRIFECTA, key))
        if key not in prev_tri:
            diff.new.append(
                Condition(
                    LETHAL_TRIFECTA,
                    key,
                    f"{label}: new lethal trifecta in {entry['file']}",
                    "critical",
                    {"where": _where(entry), "detail": entry["detail"], "fix": entry.get("fix")},
                )
            )

    cur_ungoverned = {k for k, v in cur_gov.items() if not v.get("governed")}
    prev_governed = {k for k, v in prev_gov.items() if v.get("governed")}
    for key in sorted(cur_ungoverned):
        entry = cur_gov[key]
        what = "model call" if entry["kind"] == "model_call" else "agent entrypoint"
        evidence = {
            "where": _where(entry),
            "call": entry["detail"],
            "provider": entry.get("provider"),
        }
        diff.holding.add((GOVERNANCE_REMOVED, key))
        diff.holding.add((UNGOVERNED_MODEL_CALL, key))
        if key in prev_governed:
            diff.new.append(
                Condition(
                    GOVERNANCE_REMOVED,
                    key,
                    f"{label}: governance removed from a {what} in {entry['file']}",
                    "high",
                    evidence,
                )
            )
        elif key not in prev_gov:
            diff.new.append(
                Condition(
                    UNGOVERNED_MODEL_CALL,
                    key,
                    f"{label}: new ungoverned {what} in {entry['file']}",
                    "high",
                    evidence,
                )
            )

    for key, entry in cur_tools.items():
        diff.holding.add((NEW_TOOL, key))
        if key not in prev_tools:
            caps = entry.get("capabilities") or []
            diff.new.append(
                Condition(
                    NEW_TOOL,
                    key,
                    f"{label}: new tool '{entry['name']}' in {entry['file']}",
                    "medium" if caps else "low",
                    {"where": _where(entry), "tool": entry["name"], "capabilities": caps},
                )
            )

    for key, entry in cur_mcp.items():
        diff.holding.add((NEW_MCP_SERVER, key))
        if key not in prev_mcp:
            diff.new.append(
                Condition(
                    NEW_MCP_SERVER,
                    key,
                    f"{label}: new MCP server '{entry['name']}' in {entry['file']}",
                    "medium",
                    {
                        "where": entry["file"],
                        "server": entry["name"],
                        "detail": entry.get("detail"),
                        "capabilities": entry.get("capabilities") or [],
                    },
                )
            )

    def _delta(prev: dict[str, Any], cur: dict[str, Any]) -> tuple[list[str], list[str]]:
        return sorted(set(cur) - set(prev)), sorted(set(prev) - set(cur))

    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for name, prev, cur in (
        ("lethal_trifectas", prev_tri, cur_tri),
        ("model_calls", prev_gov, cur_gov),
        ("tools", prev_tools, cur_tools),
        ("mcp_servers", prev_mcp, cur_mcp),
    ):
        plus, minus = _delta(prev, cur)
        if plus:
            added[name] = plus
        if minus:
            removed[name] = minus
    newly_governed = sorted(
        k
        for k, v in cur_gov.items()
        if v.get("governed") and k in prev_gov and k not in prev_governed
    )
    diff.changes = {
        "added": added,
        "removed": removed,
        "newly_governed": newly_governed,
        "governance_removed": sorted(c.key for c in diff.new if c.type == GOVERNANCE_REMOVED),
    }
    return diff


# ---------------------------------------------------------------------------
# Hosted APIs (OpenAPI)
# ---------------------------------------------------------------------------

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")
#: A POST whose path or summary says one of these is treated as destructive too:
#: plenty of APIs delete, pay or send through POST.
_DESTRUCTIVE_WORDS = re.compile(
    r"\b(?:delete|remove|destroy|purge|drop|wipe|revoke|transfer|pay|payout|refund|charge|"
    r"send|email|execute|exec|run|shell|admin|grant|impersonate)\b",
    re.I,
)


def _words(text: str) -> str:
    # Split camelCase and path punctuation so `deleteUser` and `/users/{id}/purge` match.
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", re.sub(r"[/_{}\-.]", " ", text))


def is_destructive(method: str, path: str, summary: str = "") -> bool:
    method = method.lower()
    if method in ("delete", "put", "patch"):
        return True
    return method == "post" and bool(_DESTRUCTIVE_WORDS.search(_words(f"{path} {summary}")))


def api_snapshot(spec: dict[str, Any]) -> dict[str, Any]:
    """Every operation in an OpenAPI document, keyed ``METHOD /path``."""
    operations: dict[str, Any] = {}
    paths = spec.get("paths")
    if isinstance(paths, dict):
        for path, ops in paths.items():
            if not isinstance(ops, dict):
                continue
            for method, op in ops.items():
                m = str(method).lower()
                if m not in _HTTP_METHODS or not isinstance(op, dict):
                    continue
                summary = str(op.get("summary") or op.get("operationId") or "")
                operations[f"{m.upper()} {path}"] = {
                    "method": m.upper(),
                    "path": str(path),
                    "summary": summary[:200],
                    "destructive": is_destructive(m, str(path), summary),
                }
    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
    return {
        "type": "openapi",
        "title": str(info.get("title") or ""),
        "version": str(info.get("version") or ""),
        "operations": operations,
    }


def diff_api(previous: dict[str, Any], current: dict[str, Any], *, label: str) -> Diff:
    diff = Diff(managed_types=API_TYPES)
    prev_ops = previous.get("operations") or {}
    cur_ops = current.get("operations") or {}
    for key, op in sorted(cur_ops.items()):
        kind = API_DESTRUCTIVE_ENDPOINT if op.get("destructive") else API_NEW_ENDPOINT
        diff.holding.add((kind, key))
        if key in prev_ops:
            continue
        if op.get("destructive"):
            title = f"{label}: new destructive endpoint {key}"
            severity = "high"
        else:
            title = f"{label}: new endpoint {key}"
            severity = "low"
        diff.new.append(
            Condition(
                kind,
                key,
                title,
                severity,
                {"operation": key, "summary": op.get("summary"), "destructive": op["destructive"]},
            )
        )
    became_destructive = sorted(
        k
        for k, op in cur_ops.items()
        if op.get("destructive") and k in prev_ops and not prev_ops[k].get("destructive")
    )
    added = sorted(set(cur_ops) - set(prev_ops))
    removed = sorted(set(prev_ops) - set(cur_ops))
    diff.changes = {
        "added": {"operations": added} if added else {},
        "removed": {"operations": removed} if removed else {},
        "became_destructive": became_destructive,
        "version": [previous.get("version"), current.get("version")]
        if previous.get("version") != current.get("version")
        else None,
    }
    return diff


def summarise(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Counts for `Monitor.last_result_json` — never the whole snapshot."""
    if snapshot.get("type") == "repo":
        gov = snapshot.get("governable") or {}
        return {
            "files_scanned": snapshot.get("files_scanned"),
            "inconclusive": snapshot.get("inconclusive"),
            "frameworks": snapshot.get("frameworks") or [],
            "lethal_trifectas": len(snapshot.get("trifectas") or {}),
            "model_calls": len(gov),
            "ungoverned": sum(1 for v in gov.values() if not v.get("governed")),
            "tools": len(snapshot.get("tools") or {}),
            "mcp_servers": len(snapshot.get("mcp_servers") or {}),
        }
    if snapshot.get("type") == "openapi":
        ops = snapshot.get("operations") or {}
        return {
            "title": snapshot.get("title"),
            "version": snapshot.get("version"),
            "operations": len(ops),
            "destructive": sum(1 for v in ops.values() if v.get("destructive")),
        }
    return {k: v for k, v in snapshot.items() if not isinstance(v, dict | list)}
