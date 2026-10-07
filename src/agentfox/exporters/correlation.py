"""LangSmith and Langfuse correlation.

The practitioner evidence is unambiguous: teams already run LangSmith or Langfuse,
and they are not going to stop. Six of eleven engineers had additionally hand-rolled
a governance wrapper *beside* that observability stack, which produced the failure
this module exists to remove — **two systems that both claim to describe the same
request and cannot be joined**. An incident then costs an engineer twenty minutes of
timestamp arithmetic to answer "which decision shaped this trace?".

The design constraint is that we must not become a second SDK a team installs. So:

* **No hard dependency.** Correlation works with zero packages installed, because the
  join key travels in-band — a W3C ``traceparent`` header, or the vendor's own trace
  header. Both LangSmith and Langfuse speak OTLP, so this is their format, not ours.
* **Bidirectional by construction.** A link is stored once and read from either end:
  our trace to their run, and their run id back to our decision. The reverse
  direction is the one that matters during an incident and the one nobody ships.
* **Push is optional and best-effort.** Writing our verdict back onto their run makes
  the governance decision visible where the engineer is already looking. It requires
  egress plus a key, it never blocks enforcement, and a failure is recorded rather
  than raised — a governance control that takes the request down when an
  observability vendor has an outage is a worse control than none.

What we deliberately do **not** do is re-ingest their traces. Their span store is
better than ours and duplicating it would make us a worse LangSmith. We store the
join key and the deep link, and let each system keep what it is good at.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import TraceLink

log = logging.getLogger(__name__)

LANGSMITH = "langsmith"
LANGFUSE = "langfuse"
OTEL = "otel"
SYSTEMS = (LANGSMITH, LANGFUSE, OTEL)

# W3C Trace Context: version-traceid(32 hex)-spanid(16 hex)-flags.
_TRACEPARENT = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace>[0-9a-f]{32})-(?P<span>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)

# Header names we accept, most specific first. Vendor SDKs and proxies disagree on
# spelling, and a join key missed because of a hyphen is a join key we do not have.
# The pre-rename x-nometria-* spelling is still accepted, after x-agentfox-*.
_HEADER_MAP: list[tuple[str, tuple[str, ...]]] = [
    (
        LANGSMITH,
        (
            "x-agentfox-langsmith-trace",
            "x-nometria-langsmith-trace",
            "langsmith-trace-id",
            "x-langsmith-trace-id",
        ),
    ),
    (
        LANGFUSE,
        (
            "x-agentfox-langfuse-trace",
            "x-nometria-langfuse-trace",
            "langfuse-trace-id",
            "x-langfuse-trace-id",
        ),
    ),
]
_RUN_HEADER_MAP: list[tuple[str, tuple[str, ...]]] = [
    (LANGSMITH, ("langsmith-run-id", "x-langsmith-run-id")),
    (LANGFUSE, ("langfuse-observation-id", "x-langfuse-observation-id")),
]


@dataclass(frozen=True)
class ExternalRef:
    """One external system's identifiers for the same logical request."""

    system: str
    external_trace_id: str
    external_run_id: str | None = None
    project: str | None = None

    def url(self) -> str | None:
        return deep_link(self.system, self.external_trace_id, self.project)


# ---------------------------------------------------------------------------
# Deep links
# ---------------------------------------------------------------------------


def deep_link(system: str, external_trace_id: str, project: str | None = None) -> str | None:
    """Build a URL an engineer can click, or None when we cannot know the host.

    Self-hosted Langfuse and self-hosted LangSmith both live on customer domains, so
    the base URL is configuration. Guessing a SaaS URL for a self-hosted deployment
    produces a link that 404s, which is worse than no link.
    """
    settings = get_settings()
    trace = quote(external_trace_id, safe="")
    if system == LANGSMITH:
        base = (settings.langsmith_ui_url or "").rstrip("/")
        if not base:
            return None
        proj = quote(project or settings.langsmith_project or "-")
        return f"{base}/o/-/projects/p/{proj}/r/{trace}"
    if system == LANGFUSE:
        base = (settings.langfuse_host or "").rstrip("/")
        if not base:
            return None
        return f"{base}/trace/{trace}"
    return None


# ---------------------------------------------------------------------------
# Inbound: read the join key off the request
# ---------------------------------------------------------------------------


def refs_from_headers(headers: dict[str, str] | Any) -> list[ExternalRef]:
    """Extract external references from request headers.

    Accepts anything with case-insensitive ``get`` (Starlette's ``Headers``) or a
    plain dict, which is what the SDK and the LangGraph guard pass.
    """
    lower = {str(k).lower(): str(v) for k, v in dict(headers).items()} if headers else {}
    runs = {
        system: lower[name]
        for system, names in _RUN_HEADER_MAP
        for name in names
        if lower.get(name)
    }

    refs: list[ExternalRef] = []
    seen: set[str] = set()
    for system, names in _HEADER_MAP:
        for name in names:
            value = lower.get(name)
            if value and system not in seen:
                seen.add(system)
                refs.append(
                    ExternalRef(
                        system=system, external_trace_id=value, external_run_id=runs.get(system)
                    )
                )

    # W3C trace context is the vendor-neutral fallback and the one that arrives
    # automatically when a team already runs an OTel SDK — no header configuration,
    # no vendor lock, and it correlates with anything downstream of their collector.
    parent = lower.get("traceparent")
    if parent:
        match = _TRACEPARENT.match(parent.strip())
        if match:
            refs.append(
                ExternalRef(
                    system=OTEL,
                    external_trace_id=match.group("trace"),
                    external_run_id=match.group("span"),
                )
            )
    return refs


def refs_from_env() -> list[ExternalRef]:
    """Pick up ambient context from an in-process LangSmith/Langfuse SDK, if present.

    Import-guarded on purpose: the whole point is that a team gets correlation without
    installing anything, so a missing package is the normal case, not an error.
    """
    refs: list[ExternalRef] = []
    try:  # pragma: no cover - exercised only where langsmith is installed
        from langsmith.run_helpers import get_current_run_tree

        tree = get_current_run_tree()
        if tree is not None and getattr(tree, "trace_id", None):
            refs.append(
                ExternalRef(
                    system=LANGSMITH,
                    external_trace_id=str(tree.trace_id),
                    external_run_id=str(getattr(tree, "id", "") or "") or None,
                    project=getattr(tree, "session_name", None),
                )
            )
    except Exception:
        pass
    try:  # pragma: no cover - exercised only where langfuse is installed
        from langfuse.decorators import langfuse_context

        current = langfuse_context.get_current_trace_id()
        if current:
            refs.append(
                ExternalRef(
                    system=LANGFUSE,
                    external_trace_id=str(current),
                    external_run_id=langfuse_context.get_current_observation_id(),
                )
            )
    except Exception:
        pass
    return refs


# ---------------------------------------------------------------------------
# Storage — the bidirectional index
# ---------------------------------------------------------------------------


def link_trace(
    session: Session,
    trace_id: str,
    refs: list[ExternalRef],
    *,
    direction: str = "inbound",
) -> list[TraceLink]:
    """Record the join keys. Idempotent per (trace, system, external trace)."""
    created: list[TraceLink] = []
    for ref in refs:
        if ref.system not in SYSTEMS or not ref.external_trace_id:
            continue
        existing = session.scalar(
            select(TraceLink).where(
                TraceLink.trace_id == trace_id,
                TraceLink.system == ref.system,
                TraceLink.external_trace_id == ref.external_trace_id,
            )
        )
        if existing is not None:
            if ref.external_run_id and not existing.external_run_id:
                existing.external_run_id = ref.external_run_id
            continue
        link = TraceLink(
            trace_id=trace_id,
            system=ref.system,
            external_trace_id=ref.external_trace_id,
            external_run_id=ref.external_run_id,
            project=ref.project or _default_project(ref.system),
            url=ref.url(),
            direction=direction,
        )
        session.add(link)
        created.append(link)
    if created:
        session.flush()
    return created


def links_for(session: Session, trace_id: str) -> list[TraceLink]:
    stmt = select(TraceLink).where(TraceLink.trace_id == trace_id).order_by(TraceLink.system)
    return list(session.scalars(stmt))


def resolve_external(session: Session, system: str, external_id: str) -> list[TraceLink]:
    """The reverse direction: their run id → our governance decision.

    Matches on either the external trace or the external run/observation id, because
    an engineer copying an id out of a Langfuse UI does not know or care which of the
    two they grabbed.
    """
    return list(
        session.scalars(
            select(TraceLink).where(
                TraceLink.system == system,
                (TraceLink.external_trace_id == external_id)
                | (TraceLink.external_run_id == external_id),
            )
        )
    )


def _default_project(system: str) -> str | None:
    settings = get_settings()
    if system == LANGSMITH:
        return settings.langsmith_project
    if system == LANGFUSE:
        return settings.langfuse_project
    return None


# ---------------------------------------------------------------------------
# Outbound: write the verdict back where the engineer is already looking
# ---------------------------------------------------------------------------


@dataclass
class PushResult:
    system: str
    ok: bool
    detail: str = ""


def push_verdict(
    session: Session,
    trace_id: str,
    *,
    verdict: str,
    effective_verdict: str | None = None,
    rules: list[str] | None = None,
    agent_slug: str | None = None,
) -> list[PushResult]:
    """Annotate the external run with our decision. Best-effort, never raises.

    Gated on ``allow_egress`` like every other outbound path: a governance
    product that phones out by default cannot be deployed in the environments that
    need it most.
    """
    settings = get_settings()
    results: list[PushResult] = []
    if not settings.allow_egress or not settings.correlation_push:
        return results

    payload_tags = [f"agentfox:{verdict}"]
    if effective_verdict and effective_verdict != verdict:
        payload_tags.append(f"agentfox-effective:{effective_verdict}")
    metadata = {
        "agentfox_trace_id": trace_id,
        "agentfox_verdict": verdict,
        "agentfox_effective_verdict": effective_verdict or verdict,
        "agentfox_rules": rules or [],
        "agentfox_agent": agent_slug,
    }

    for link in links_for(session, trace_id):
        if link.system == LANGSMITH:
            results.append(_push_langsmith(link, metadata, payload_tags))
        elif link.system == LANGFUSE:
            results.append(_push_langfuse(link, metadata, payload_tags))
    for result in results:
        link_status = "ok" if result.ok else "failed"
        log.debug("correlation push %s: %s (%s)", result.system, link_status, result.detail)
    return results


def _push_langsmith(link: TraceLink, metadata: dict[str, Any], tags: list[str]) -> PushResult:
    settings = get_settings()
    if not settings.langsmith_api_key:
        return PushResult(LANGSMITH, False, "no api key")
    run_id = link.external_run_id or link.external_trace_id
    try:
        import httpx

        response = httpx.patch(
            f"{settings.langsmith_api_url.rstrip('/')}/runs/{run_id}",
            headers={"x-api-key": settings.langsmith_api_key},
            json={"extra": {"metadata": metadata}, "tags": tags},
            timeout=settings.correlation_timeout_seconds,
        )
        return PushResult(LANGSMITH, response.status_code < 400, f"http {response.status_code}")
    except Exception as exc:  # never let an observability vendor take the request down
        return PushResult(LANGSMITH, False, str(exc))


def _push_langfuse(link: TraceLink, metadata: dict[str, Any], tags: list[str]) -> PushResult:
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return PushResult(LANGFUSE, False, "no api key")
    try:
        import httpx

        response = httpx.post(
            f"{settings.langfuse_host.rstrip('/')}/api/public/traces",
            auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
            json={"id": link.external_trace_id, "metadata": metadata, "tags": tags},
            timeout=settings.correlation_timeout_seconds,
        )
        return PushResult(LANGFUSE, response.status_code < 400, f"http {response.status_code}")
    except Exception as exc:
        return PushResult(LANGFUSE, False, str(exc))


class TraceCorrelation:
    """The runtime's trace exporter (`agentfox.runtime.trace_exporters`): links a governed
    trace to the caller's LangSmith/Langfuse/OTel trace and pushes its verdicts there."""

    def link(self, session: Session, trace_id: str, correlation: Any) -> None:
        """Record the caller's external references, from headers, a list, or the env."""
        if isinstance(correlation, dict):
            refs = refs_from_headers(correlation)
        elif correlation:
            refs = list(correlation)
        else:
            refs = []
        refs = refs + refs_from_env()
        if refs:
            link_trace(session, trace_id, refs)

    def push(
        self,
        session: Session,
        trace_id: str,
        *,
        verdict: str,
        effective_verdict: str,
        rules: list[str],
        agent_slug: str | None,
    ) -> None:
        push_verdict(
            session,
            trace_id,
            verdict=verdict,
            effective_verdict=effective_verdict,
            rules=rules,
            agent_slug=agent_slug,
        )
