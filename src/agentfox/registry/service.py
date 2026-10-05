"""Pillar 1 — Discovery & Agent Registry.

The design commitment that separates this from a GRC incumbent's registry: **lineage
is observed, not declared.** Credo AI and OneTrust model a self-reported form; a
registry that only knows what someone typed into it is the spreadsheet Dana already
has. Every edge here is derived from spans the agent actually produced, and a
divergence between declared and observed is itself a finding (P1-7).

Shadow-agent detection (P1-2) is the same idea applied to the population: traffic
that does not correlate to a registered agent creates the agent record, marked
unregistered, with a ready-to-submit registration payload attached. Discovery that
requires the shadow team to cooperate discovers nothing.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentfox.core.models import (
    Agent,
    Finding,
    LineageEdge,
    McpServer,
    McpToolSnapshot,
    Span,
    Tool,
    Trace,
    as_aware,
    utcnow,
)
from agentfox.policy import PolicyDocument, save_policy
from agentfox.prove.findings import auto_resolve, raise_finding, resolve_finding

_SLUG = re.compile(r"[^a-z0-9-]+")


def slugify(value: str) -> str:
    return _SLUG.sub("-", (value or "unknown").strip().lower()).strip("-") or "unknown"


def _get_or_create(session: Session, model: type, **lookup: Any) -> Any:
    """Find a row by its unique lookup column, or create and stage a fresh one.

    `register_agent`, `upsert_tool` and `upsert_mcp_server` each hand-rolled this
    exact find-or-add skeleton before their own field-by-field merge logic; this is
    the one copy of it.
    """
    row = session.scalar(select(model).filter_by(**lookup))
    if row is None:
        row = model(**lookup)
        session.add(row)
    return row


# ---------------------------------------------------------------------------
# Registration & observation
# ---------------------------------------------------------------------------


def register_agent(
    session: Session,
    slug: str,
    *,
    name: str = "",
    purpose: str = "",
    owner_email: str | None = None,
    owner_team: str | None = None,
    environment: str = "production",
    risk_tier: str = "limited",
    declared_models: list[str] | None = None,
    declared_tools: list[str] | None = None,
    data_classes: list[str] | None = None,
    framework: str | None = None,
    draft: bool = False,
    source_scan_run_id: str | None = None,
) -> Agent:
    """Register (or upsert) an agent.

    ``draft=True`` is the repo-scan path (routes/integrations.py): the agent is
    created inert — ``status="draft"``, ``registered=False`` — so nothing treats it
    as live until a human approves it. Approval just flips those two fields, it does
    not re-run this function.
    """
    slug = slugify(slug)
    agent = _get_or_create(session, Agent, slug=slug)

    agent.name = name or agent.name or slug
    agent.purpose = purpose or agent.purpose
    agent.owner_email = owner_email or agent.owner_email
    agent.owner_team = owner_team or agent.owner_team
    agent.environment = environment
    agent.risk_tier = risk_tier
    agent.framework = framework or agent.framework
    agent.declared_models = declared_models or agent.declared_models or []
    agent.declared_tools = declared_tools or agent.declared_tools or []
    agent.data_classes = data_classes or agent.data_classes or []
    if source_scan_run_id:
        agent.source_scan_run_id = source_scan_run_id
    if draft:
        agent.registered = False
        agent.status = "draft"
    else:
        agent.registered = True
        agent.status = "active"
    if agent.first_seen_at is None:
        agent.first_seen_at = utcnow()
    session.flush()
    return agent


def propose_from_scan(
    session: Session,
    *,
    run_id: str,
    repo_slug_base: str,
    repo_display_name: str,
    frameworks: list[str],
    sites: list[dict[str, Any]],
    author: str,
) -> tuple[list[str], list[str]]:
    """Propose one draft agent per top-level directory and one observe-mode policy
    per detected framework, from a discovery scan's governable sites.

    Shared by every scan entry point that ends up here — the GitHub-connected repo
    scan (``routes/integrations.py``) and a locally-run ``agentfox scan --submit`` /
    ``agentfox scan --sessions --submit`` (``routes/discovery.py``) — so a scan looks the
    same in the dashboard whichever door it came through. ``sites`` is intentionally
    the redacted shape (``{"kind", "top_dir", "provider"}``, see
    ``discovery.ScanReport.to_submission_payload``): this function never needs, and
    must never be given, a file's full path, line number or literal source text.
    """
    repo_short = slugify(repo_slug_base)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # A lethal trifecta (private data + untrusted input + a way out, see
    # `agentfox.discovery.exposure`) raises the risk tier of the agent in its directory. It
    # does not propose an agent on its own: an `.mcp.json` trifecta describes an
    # IDE's servers, not an application this repo deploys.
    trifecta_dirs: set[str] = set()
    for site in sites:
        if site.get("kind") == "lethal_trifecta":
            trifecta_dirs.add(site.get("top_dir") or "root")
            continue
        groups[site.get("top_dir") or "root"].append(site)

    created_agents: list[str] = []
    for group_key, group_sites in groups.items():
        providers = [s["provider"] for s in group_sites if s.get("provider")]
        framework = providers[0] if providers else (frameworks[0] if frameworks else None)
        # A monorepo's top-level directory is often named after the repo itself
        # (e.g. gpt-researcher/gpt-researcher/) — slugifying both halves would
        # produce "gpt-researcher-gpt-researcher", which reads as a typo rather
        # than two distinct things.
        group_slug = slugify(group_key)
        slug = repo_short if group_slug == repo_short else f"{repo_short}-{group_slug}"
        agent = register_agent(
            session,
            slug=slug,
            name=f"{repo_display_name}/{group_key}",
            # A static scan can count code sites, not know what the agent is
            # *for* — left blank and surfaced honestly until a human sets one.
            purpose="",
            framework=framework,
            # Proposed, like the rest of a draft: a human confirms the class on
            # approval (`compliance.risk.classify` explains why it is a proposal).
            risk_tier="high" if group_key in trifecta_dirs else "limited",
            draft=True,
            source_scan_run_id=run_id,
        )
        created_agents.append(agent.slug)

    created_policies: list[str] = []
    for framework in frameworks:
        doc = PolicyDocument(
            key=f"scan-{run_id}-{slugify(framework)}",
            name=f"{framework} guardrails",
            description=(
                f"Detects {framework} usage in {repo_display_name} — prompt "
                f"injection, PII/secret leaks, and unsafe tool actions."
            ),
            mode="observe",
            scope={"agents": [f"{repo_short}-*"]},
            rules=[],
        )
        policy, _version = save_policy(
            session,
            doc,
            author=author,
            notes=f"Proposed by scan {run_id}",
            bind_mode="observe",
        )
        policy.proposed = True
        policy.source_scan_run_id = run_id
        created_policies.append(policy.key)

    return created_agents, created_policies


def observe_agent(
    session: Session,
    slug: str,
    *,
    environment: str = "production",
    model: str | None = None,
    framework: str | None = None,
) -> tuple[Agent, bool]:
    """Record that an agent was seen. Returns ``(agent, is_new_shadow)``.

    Called on every gateway request and every ingested OTel batch, which is what
    makes P1-2 work without asking anyone to cooperate.
    """
    slug = slugify(slug)
    agent = session.scalar(select(Agent).where(Agent.slug == slug))
    is_new_shadow = False

    if agent is None:
        agent = Agent(
            slug=slug,
            name=slug,
            environment=environment,
            registered=False,
            status="shadow",
            risk_tier="limited",
            first_seen_at=utcnow(),
        )
        session.add(agent)
        session.flush()
        is_new_shadow = True
        raise_finding(
            session,
            type="shadow_agent",
            severity="high",
            title=f"Ungoverned agent '{slug}' observed in {environment}",
            subject_type="agent",
            subject_id=agent.id,
            evidence={
                "slug": slug,
                "environment": environment,
                "model": model,
                "framework": framework,
                "first_seen": utcnow().isoformat(),
                # A finding you can act on in one click beats a finding you have
                # to translate into a form.
                "suggested_registration": {
                    "slug": slug,
                    "name": slug,
                    "environment": environment,
                    "owner_email": None,
                    "purpose": "",
                    "risk_tier": "limited",
                    "declared_models": [model] if model else [],
                },
            },
            control_keys=["NOM-DSC-01", "NOM-DSC-02"],
        )

    # Debounced, not unconditional: a single governed call can resolve the same
    # agent from more than one DB session in quick succession (e.g. autoguard's
    # pre-flight check opens its own session independently of whatever session a
    # caller already has open around the whole call — see autoguard.py's
    # `_govern`). Writing `last_seen_at` from both stalls one session behind the
    # other's uncommitted row lock — on Postgres, with no lock_timeout configured,
    # that's an unbounded hang, not a slow query. Found live: a deployed demo
    # whose request holds a session open across an `AgentExecutor.invoke()`,
    # which itself triggers a second, independent resolve of the very same agent
    # mid-call. Skipping the redundant write when the row was already touched a
    # moment ago removes the second writer instead of just widening the window.
    now = utcnow()
    last_seen = as_aware(agent.last_seen_at)
    if last_seen is None or (now - last_seen) > dt.timedelta(seconds=5):
        agent.last_seen_at = now
    if framework and not agent.framework:
        agent.framework = framework
    if model and model not in (agent.declared_models or []):
        # Observed, not declared — surfaced separately by attest_registry().
        pass
    session.flush()
    return agent, is_new_shadow


def detect_shadow_agents(session: Session, window_days: int = 30) -> list[dict[str, Any]]:
    """Report every unregistered agent with the evidence to act on it.

    Excludes "draft" (proposed by a repo scan, never ran) and "rejected" (a draft a
    human already declined) — both are unregistered, but neither is what "shadow"
    means here: traffic that ran without anyone registering it first.
    """
    since = utcnow() - dt.timedelta(days=window_days)
    out: list[dict[str, Any]] = []
    for agent in session.scalars(
        select(Agent).where(Agent.registered.is_(False), Agent.status.notin_(("draft", "rejected")))
    ):
        traces = list(
            session.scalars(
                select(Trace).where(Trace.agent_slug == agent.slug, Trace.started_at >= since)
            )
        )
        out.append(
            {
                "slug": agent.slug,
                "environment": agent.environment,
                "first_seen": agent.first_seen_at.isoformat() if agent.first_seen_at else None,
                "last_seen": agent.last_seen_at.isoformat() if agent.last_seen_at else None,
                "calls": len(traces),
                "models": sorted({t.model for t in traces if t.model}),
                "providers": sorted({t.provider for t in traces if t.provider}),
                "framework": agent.framework,
                "suggested_registration": {
                    "slug": agent.slug,
                    "name": agent.name or agent.slug,
                    "environment": agent.environment,
                    "declared_models": sorted({t.model for t in traces if t.model}),
                },
            }
        )
    return out


def unowned_agents(session: Session) -> list[Finding]:
    """An unowned agent is a reportable compliance finding (P1-4, NOM-DSC-03)."""
    findings: list[Finding] = []
    for agent in list(session.scalars(select(Agent).where(Agent.status != "retired"))):
        if agent.is_owned:
            # The condition cleared: someone took ownership since the last scan.
            auto_resolve(
                session,
                type="unowned_agent",
                subject_type="agent",
                subject_id=agent.id,
                note=f"agent '{agent.slug}' now has an accountable owner",
            )
            continue
        finding, _ = raise_finding(
            session,
            type="unowned_agent",
            severity="medium",
            title=f"Agent '{agent.slug}' has no accountable owner",
            subject_type="agent",
            subject_id=agent.id,
            evidence={"slug": agent.slug, "environment": agent.environment},
            control_keys=["NOM-DSC-03", "NOM-GOV-03"],
        )
        findings.append(finding)
    session.flush()
    return findings


# ---------------------------------------------------------------------------
# Tools & lineage
# ---------------------------------------------------------------------------

#: Tool key -> impact, for every `@fox.tool(key, impact=...)` declared in this
#: process. The decorator also writes the row, but it runs at import time, which can
#: be before the database exists; this is what `auto()` consults when it registers a
#: tool the model called, so a declaration made in code beats a guess from the name
#: even when that write could not happen yet.
DECLARED_TOOL_IMPACTS: dict[str, str] = {}

#: Marks a tool whose `impact` was guessed — from its name and description, when
#: `auto()` or MCP governance first saw it — rather than declared by an operator,
#: the CLI/API or code. Kept as a JSON Schema vendor keyword in `schema_json`
#: rather than a column of its own on purpose: a deployment runs new code before
#: anyone runs its migration (tests/gateway/test_playground.py pins that window), and a
#: new column on `tools` would break every tool lookup in it, the enforcement path
#: included. Validators ignore `x-` keywords; `tool_input_schema` strips it.
IMPACT_SOURCE_KEY = "x-agentfox-impact-source"


def impact_source_of(tool: Tool) -> str:
    """``inferred`` for a guessed impact awaiting confirmation, else ``declared``."""
    schema = tool.schema_json or {}
    return "inferred" if schema.get(IMPACT_SOURCE_KEY) == "inferred" else "declared"


def tool_input_schema(tool: Tool) -> dict[str, Any]:
    """The tool's input schema as the tool itself declared it, without our marker."""
    return {k: v for k, v in (tool.schema_json or {}).items() if k != IMPACT_SOURCE_KEY}


def upsert_tool(
    session: Session,
    key: str,
    *,
    name: str = "",
    kind: str = "function",
    impact: str = "read",
    schema: dict[str, Any] | None = None,
    description: str = "",
    mcp_server_id: str | None = None,
    impact_source: str = "declared",
    output_trust: str | None = None,
) -> Tool:
    """Create or update a tool. ``output_trust=None`` leaves the declared trust as it is."""
    tool = _get_or_create(session, Tool, key=key)
    tool.name = name or tool.name or key
    tool.kind = kind
    tool.impact = impact
    # A fresh dict, so the JSON column registers the change; a declaration clears
    # the inferred marker, which is how `agentfox declare tool` confirms a guess.
    schema_json = dict(schema or tool.schema_json or {})
    if impact_source == "inferred":
        schema_json[IMPACT_SOURCE_KEY] = "inferred"
    else:
        schema_json.pop(IMPACT_SOURCE_KEY, None)
    tool.schema_json = schema_json
    tool.description = description or tool.description
    tool.mcp_server_id = mcp_server_id or tool.mcp_server_id
    if output_trust is not None:
        tool.output_trust = output_trust
    elif not tool.output_trust:
        tool.output_trust = "untrusted"
    session.flush()
    return tool


def record_edge(
    session: Session,
    src_type: str,
    src_id: str,
    dst_type: str,
    dst_id: str,
    relation: str,
    declared: bool = False,
) -> LineageEdge:
    """Record an observed (or declared) lineage edge, idempotent under races.

    The existence check below and the insert it guards are two separate
    round-trips, so two callers recording the same edge for the first time at
    nearly the same moment (two concurrent requests each building their own
    `McpGovernor` — the ordinary case for this same edge, "agent connects_mcp
    server", which gets (re-)recorded on every governed call) can both pass the
    check before either commits. The second one then hits uq_lineage_edge's
    UniqueViolation on flush — found live, a real deployed request crashed this
    way, not a theoretical race. The insert attempt runs in its own SAVEPOINT
    (`begin_nested`) so a lost race only unwinds that nested transaction, not
    the whole session — SQLAlchemy expunges the losing pending object on
    rollback — and falls through to the row the winner just committed.
    """
    edge = session.scalar(
        select(LineageEdge).where(
            LineageEdge.src_id == src_id,
            LineageEdge.dst_id == dst_id,
            LineageEdge.relation == relation,
        )
    )
    if edge is None:
        try:
            with session.begin_nested():
                edge = LineageEdge(
                    src_type=src_type,
                    src_id=src_id,
                    dst_type=dst_type,
                    dst_id=dst_id,
                    relation=relation,
                    declared=declared,
                    # Set explicitly: the column default is applied at flush,
                    # and this counter is incremented before the flush happens.
                    observed_count=0,
                )
                session.add(edge)
                session.flush()
        except IntegrityError:
            edge = session.scalar(
                select(LineageEdge).where(
                    LineageEdge.src_id == src_id,
                    LineageEdge.dst_id == dst_id,
                    LineageEdge.relation == relation,
                )
            )
    edge.observed_count += 0 if declared else 1
    edge.last_observed_at = utcnow()
    if declared:
        edge.declared = True
    session.flush()
    return edge


def derive_lineage(session: Session, agent_slug: str | None = None) -> int:
    """Rebuild the lineage graph from observed spans (P1-3)."""
    query = select(Trace)
    if agent_slug:
        query = query.where(Trace.agent_slug == agent_slug)
    edges = 0
    for trace in session.scalars(query):
        if not trace.agent_slug:
            continue
        if trace.model:
            record_edge(session, "agent", trace.agent_slug, "model", trace.model, "uses_model")
            edges += 1
        for span in session.scalars(select(Span).where(Span.trace_id == trace.id)):
            attrs = span.attributes_json or {}
            if span.kind == "tool":
                tool_key = str(attrs.get("gen_ai.tool.name") or span.name)
                record_edge(session, "agent", trace.agent_slug, "tool", tool_key, "calls_tool")
                edges += 1
                server = attrs.get("agentfox.integrations.mcp_server")
                if server:
                    record_edge(
                        session, "tool", tool_key, "mcp_server", str(server), "connects_mcp"
                    )
                    edges += 1
            elif span.kind == "retrieval":
                source = str(attrs.get("agentfox.data_source") or span.name)
                record_edge(session, "agent", trace.agent_slug, "data_source", source, "reads_data")
                edges += 1
            elif span.kind == "subagent":
                child = str(attrs.get("agentfox.child_agent") or span.name)
                record_edge(session, "agent", trace.agent_slug, "agent", child, "delegates_to")
                edges += 1
    return edges


def lineage(session: Session, agent_slug: str, depth: int = 2) -> dict[str, Any]:
    """Blast-radius query: what does this agent reach, and what reaches it?"""
    nodes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(agent_slug, 0)])

    while queue:
        current, level = queue.popleft()
        if current in seen or level > depth:
            continue
        seen.add(current)

        for edge in session.scalars(select(LineageEdge).where(LineageEdge.src_id == current)):
            nodes.setdefault(edge.src_id, {"id": edge.src_id, "type": edge.src_type})
            nodes.setdefault(edge.dst_id, {"id": edge.dst_id, "type": edge.dst_type})
            links.append(
                {
                    "source": edge.src_id,
                    "target": edge.dst_id,
                    "relation": edge.relation,
                    "observed_count": edge.observed_count,
                    "declared": edge.declared,
                }
            )
            queue.append((edge.dst_id, level + 1))

        for edge in session.scalars(select(LineageEdge).where(LineageEdge.dst_id == current)):
            nodes.setdefault(edge.src_id, {"id": edge.src_id, "type": edge.src_type})
            nodes.setdefault(edge.dst_id, {"id": edge.dst_id, "type": edge.dst_type})
            links.append(
                {
                    "source": edge.src_id,
                    "target": edge.dst_id,
                    "relation": edge.relation,
                    "observed_count": edge.observed_count,
                    "declared": edge.declared,
                }
            )

    unique = {f"{link['source']}|{link['target']}|{link['relation']}": link for link in links}
    return {
        "root": agent_slug,
        "depth": depth,
        "nodes": list(nodes.values()),
        "links": list(unique.values()),
        "blast_radius": max(0, len(nodes) - 1),
    }


def attest_registry(session: Session) -> list[Finding]:
    """Compare declared configuration against observed behaviour (P1-7)."""
    findings: list[Finding] = []
    for agent in session.scalars(select(Agent).where(Agent.registered.is_(True))):
        observed_models = {
            t.model
            for t in session.scalars(select(Trace).where(Trace.agent_slug == agent.slug))
            if t.model
        }
        observed_tools = {
            e.dst_id
            for e in session.scalars(
                select(LineageEdge).where(
                    LineageEdge.src_id == agent.slug, LineageEdge.relation == "calls_tool"
                )
            )
        }
        undeclared_models = observed_models - set(agent.declared_models or [])
        undeclared_tools = observed_tools - set(agent.declared_tools or [])
        if not undeclared_models and not undeclared_tools:
            auto_resolve(
                session,
                type="registry_drift",
                subject_type="agent",
                subject_id=agent.id,
                note=f"agent '{agent.slug}' now uses only declared models and tools",
            )
            continue
        finding, _ = raise_finding(
            session,
            type="registry_drift",
            severity="medium",
            title=f"Agent '{agent.slug}' uses models/tools it has not declared",
            subject_type="agent",
            subject_id=agent.id,
            evidence={
                "undeclared_models": sorted(undeclared_models),
                "undeclared_tools": sorted(undeclared_tools),
                "declared_models": agent.declared_models,
                "declared_tools": agent.declared_tools,
            },
            control_keys=["NOM-DSC-01", "NOM-DSC-04"],
        )
        findings.append(finding)
    session.flush()
    return findings


def assess_delegation(session: Session) -> list[Finding]:
    """Detect agent-to-agent delegation cycles and runaway depth (L6.6).

    Tool-call loop detection never sees this: A delegating to B delegating back to A
    is not a repeated tool call — every call is to a different agent — so the loop is
    only visible in the shape of the delegation graph itself, built here from the
    "delegates_to" edges derive_lineage already records from subagent spans.
    """
    from agentfox.prove.attribution import delegation_graph

    edges = [
        (str(e.src_id), str(e.dst_id))
        for e in session.scalars(select(LineageEdge).where(LineageEdge.relation == "delegates_to"))
    ]
    if not edges:
        return []

    graph = delegation_graph(edges)
    findings: list[Finding] = []
    for cycle in graph.cycles:
        finding, _ = raise_finding(
            session,
            type="delegation_cycle",
            severity="high",
            title=f"Circular delegation: {' → '.join(cycle)}",
            subject_type="agent",
            subject_id=cycle[0],
            evidence={"cycle": cycle},
            control_keys=["NOM-DSC-04"],
            fingerprint_parts=tuple(cycle),
        )
        findings.append(finding)
    if graph.over_depth:
        finding, _ = raise_finding(
            session,
            type="delegation_depth",
            severity="medium",
            title=f"Delegation chain depth {graph.max_depth} exceeds the configured limit",
            subject_type="agent",
            subject_id=None,
            evidence={"max_depth": graph.max_depth},
            control_keys=["NOM-DSC-04"],
        )
        findings.append(finding)
    else:
        auto_resolve(
            session,
            type="delegation_depth",
            subject_type="agent",
            subject_id=None,
            note=f"delegation depth {graph.max_depth} is within the configured limit",
        )
    _resolve_absent(
        session,
        "delegation_cycle",
        keep={f.id for f in findings},
        note="the delegation cycle is no longer present in the observed graph",
    )
    session.flush()
    return findings


def _resolve_absent(session: Session, finding_type: str, *, keep: set[str], note: str) -> None:
    """Close open findings of a scan-produced type that this scan did not raise again."""
    for finding in list(
        session.scalars(
            select(Finding).where(Finding.type == finding_type, Finding.status == "open")
        )
    ):
        if finding.id in keep or finding.fingerprint is None:
            continue
        resolve_finding(session, finding, actor="agentfox.registry", note=note, automated=True)


# ---------------------------------------------------------------------------
# MCP inventory & hygiene (P1-5)
# ---------------------------------------------------------------------------

#: Instructions embedded in a tool *description* — the tool-poisoning shape. A
#: description is documentation for a human; imperatives aimed at the model are not
#: documentation.
_DESCRIPTION_INJECTION = [
    re.compile(r"\b(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior)\b", re.I),
    re.compile(r"\byou\s+must\s+(?:always|first|before)\b", re.I),
    re.compile(r"\b(?:do\s+not|don'?t|never)\s+(?:tell|inform|mention\s+to)\s+the\s+user\b", re.I),
    re.compile(r"<\s*(?:system|important|instructions?)\s*>", re.I),
    re.compile(
        r"\bbefore\s+(?:using|calling)\s+this\s+tool,?\s+(?:you\s+)?(?:must|should)\b", re.I
    ),
]


def upsert_mcp_server(
    session: Session,
    name: str,
    *,
    url: str = "",
    transport: str = "stdio",
    trust_level: str = "untrusted",
    pinned_version: str | None = None,
) -> McpServer:
    server = _get_or_create(session, McpServer, name=name)
    server.url = url or server.url
    server.transport = transport
    server.trust_level = trust_level
    server.pinned_version = pinned_version or server.pinned_version
    session.flush()
    return server


def scan_mcp_server(
    session: Session, server: McpServer, tools: list[dict[str, Any]]
) -> dict[str, Any]:
    """Snapshot an MCP server's tools and check hygiene.

    Two checks, both native: **schema drift** (the tools changed under us since the
    last snapshot) and **description injection** (instructions hidden in tool
    metadata). ``mcp-scan`` is invoked as an external tool when present — never
    linked as a dependency, because it is Snyk-owned and Snyk is building this
    category (Appendix A.3).
    """
    payload = json.dumps(tools, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()

    previous = session.scalars(
        select(McpToolSnapshot)
        .where(McpToolSnapshot.mcp_server_id == server.id)
        .order_by(McpToolSnapshot.captured_at.desc())
    ).first()

    snapshot = McpToolSnapshot(mcp_server_id=server.id, tools_json=tools, digest=digest)
    session.add(snapshot)
    server.last_scanned_at = utcnow()

    issues: list[dict[str, Any]] = []

    if previous is not None and previous.digest != digest:
        before = {t.get("name"): t for t in (previous.tools_json or [])}
        after = {t.get("name"): t for t in tools}
        issues.append(
            {
                "type": "schema_drift",
                "severity": "high",
                "added": sorted(set(after) - set(before)),
                "removed": sorted(set(before) - set(after)),
                "changed": sorted(
                    n
                    for n in set(before) & set(after)
                    if json.dumps(before[n], sort_keys=True) != json.dumps(after[n], sort_keys=True)
                ),
            }
        )

    for tool in tools:
        text = f"{tool.get('description', '')} {json.dumps(tool.get('inputSchema', {}))}"
        hits = [p.pattern for p in _DESCRIPTION_INJECTION if p.search(text)]
        if hits:
            issues.append(
                {
                    "type": "tool_poisoning",
                    "severity": "critical",
                    "tool": tool.get("name"),
                    "patterns": hits,
                    "excerpt": str(tool.get("description", ""))[:300],
                }
            )

    if not server.pinned_version:
        issues.append(
            {
                "type": "unpinned_server",
                "severity": "medium",
                "detail": "server has no pinned version; its tools can change silently",
            }
        )

    raised: set[str] = set()
    for issue in issues:
        finding, _ = raise_finding(
            session,
            type=issue["type"],
            severity=issue["severity"],
            title=f"MCP server '{server.name}': {issue['type'].replace('_', ' ')}",
            subject_type="mcp_server",
            subject_id=server.id,
            evidence=issue,
            control_keys=["NOM-DSC-05"],
            fingerprint_parts=(issue.get("tool"),),
        )
        raised.add(finding.id)
    # Hygiene issues this scan no longer shows are closed, so the queue reflects the
    # server as it is now. Schema drift is excluded: it describes a change between two
    # snapshots, and a later scan with no further change does not undo that change.
    for finding in list(
        session.scalars(
            select(Finding).where(
                Finding.subject_type == "mcp_server",
                Finding.subject_id == server.id,
                Finding.type.in_(("tool_poisoning", "unpinned_server")),
                Finding.status == "open",
            )
        )
    ):
        if finding.id not in raised and finding.fingerprint is not None:
            resolve_finding(
                session,
                finding,
                actor="agentfox.registry",
                note=f"scan of '{server.name}' no longer shows {finding.type.replace('_', ' ')}",
                automated=True,
            )
    session.flush()

    return {
        "server": server.name,
        "digest": digest,
        "tools": len(tools),
        "issues": issues,
        "external_scan": _external_mcp_scan(server),
    }


def _external_mcp_scan(server: McpServer) -> dict[str, Any]:
    """Invoke `mcp-scan` if the operator installed it. Tool, not dependency."""
    if not shutil.which("mcp-scan"):
        return {
            "ran": False,
            "reason": "mcp-scan not on PATH (optional external tool; Snyk-owned, "
            "deliberately not a dependency — Appendix A.3)",
        }
    try:  # pragma: no cover - requires the external binary
        proc = subprocess.run(  # noqa: S603
            ["mcp-scan", "scan", server.url or server.name, "--json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {"ran": True, "returncode": proc.returncode, "output": proc.stdout[-4000:]}
    except Exception as exc:  # pragma: no cover
        return {"ran": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Inventory summary
# ---------------------------------------------------------------------------


def inventory(session: Session) -> dict[str, Any]:
    agents = list(session.scalars(select(Agent)))
    by_tier: dict[str, int] = {}
    by_env: dict[str, int] = {}
    for agent in agents:
        by_tier[agent.risk_tier] = by_tier.get(agent.risk_tier, 0) + 1
        by_env[agent.environment] = by_env.get(agent.environment, 0) + 1
    return {
        "agents": len(agents),
        "registered": sum(1 for a in agents if a.registered),
        # "draft"/"rejected" are unregistered but were never observed running — see
        # detect_shadow_agents for why they don't belong in the same count as a
        # genuine shadow agent (traffic nobody registered first).
        "shadow": sum(
            1 for a in agents if not a.registered and a.status not in ("draft", "rejected")
        ),
        "unowned": sum(1 for a in agents if not a.is_owned),
        "by_risk_tier": by_tier,
        "by_environment": by_env,
        "frameworks": sorted({a.framework for a in agents if a.framework}),
        "tools": session.scalar(select(func.count()).select_from(Tool)) or 0,
        "mcp_servers": session.scalar(select(func.count()).select_from(McpServer)) or 0,
        "lineage_edges": session.scalar(select(func.count()).select_from(LineageEdge)) or 0,
    }
