"""Where `agentfox up` writes: this machine's database, or a control plane over HTTP.

The wizard's steps say *what* to set up (register this agent, declare these tools,
watch this repository); a backend says *where*. `Local` writes the database this
process is configured for (SQLite by default, or a shared Postgres through
`AGENTFOX_DATABASE_URL`) with the same service functions the CLI commands use.
`Remote` talks to a running gateway with an API token, which is how both a team's
self-hosted control plane and AgentFox Cloud are reached. One step list, three
deployments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class BackendError(Exception):
    """A backend could not do what a step asked. The step reports it and the wizard
    carries on with the next one."""


@dataclass
class Edition:
    """What the control plane at the other end can do."""

    name: str  # "open-source" | "enterprise"
    features: frozenset[str] = field(default_factory=frozenset)
    version: str = ""

    @property
    def enterprise(self) -> bool:
        return self.name == "enterprise"


class Backend(Protocol):
    #: "local" or "remote".
    kind: str
    #: Where it writes, for people: a database URL or a gateway URL.
    where: str

    def edition(self) -> Edition: ...

    def register_agent(self, slug: str, *, environment: str, framework: str | None) -> None: ...

    def declare_tool(self, key: str, *, impact: str, description: str) -> bool:
        """Declare a tool whose impact was inferred. False when it already exists, so a
        person's declaration is never overwritten by a guess."""
        ...

    def add_monitor(self, kind: str, target: str, *, name: str) -> bool: ...

    def register_mcp_server(self, name: str, *, url: str, transport: str) -> None: ...

    def submit_scan(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def policy_modes(self) -> dict[str, str]:
        """Each bound policy's key and live mode."""
        ...

    def set_policy_mode(self, key: str, mode: str) -> None: ...


# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------


class Local:
    kind = "local"

    def __init__(self) -> None:
        from agentfox.core.config import get_settings

        self.where = get_settings().database_url

    def _session(self):
        from agentfox.core.db import init_db, session_scope

        init_db()
        return session_scope()

    def edition(self) -> Edition:
        from agentfox import __version__
        from agentfox.core import extensions

        return Edition(
            name="enterprise" if extensions.loaded() else "open-source",
            features=extensions.features(),
            version=__version__,
        )

    def register_agent(self, slug: str, *, environment: str, framework: str | None) -> None:
        from agentfox.platform.identity import ensure_identity
        from agentfox.platform.registry.service import register_agent

        with self._session() as session:
            agent = register_agent(
                session,
                slug,
                name=slug,
                environment=environment,
                framework=framework,
                purpose="registered by agentfox up",
            )
            ensure_identity(session, agent)

    def declare_tool(self, key: str, *, impact: str, description: str) -> bool:
        from sqlalchemy import select

        from agentfox.core.models import Tool
        from agentfox.platform.registry.service import upsert_tool

        with self._session() as session:
            if session.scalar(select(Tool).where(Tool.key == key)) is not None:
                return False
            upsert_tool(
                session,
                key,
                name=key,
                impact=impact,
                description=description,
                impact_source="inferred",
                actor="agentfox up",
            )
        return True

    def add_monitor(self, kind: str, target: str, *, name: str) -> bool:
        from agentfox.core import extensions

        ensure = extensions.service("monitors.ensure")
        if ensure is None:
            raise BackendError("monitoring is an AgentFox Enterprise feature")
        with self._session() as session:
            monitor = ensure(session, kind=kind, target=target, name=name, created_by="agentfox up")
        if monitor is None:
            raise BackendError(f"could not create a monitor for {target}")
        return True

    def register_mcp_server(self, name: str, *, url: str, transport: str) -> None:
        from agentfox.core import extensions
        from agentfox.platform.registry.service import upsert_mcp_server

        ensure = extensions.service("monitors.ensure")
        with self._session() as session:
            server = upsert_mcp_server(session, name=name, url=url, transport=transport)
            if ensure is not None:
                # Watching it for tool drift is Enterprise; registering it is not.
                ensure(
                    session,
                    kind="mcp_server",
                    target=server.name,
                    name=server.name,
                    created_by="agentfox up",
                )

    def policy_modes(self) -> dict[str, str]:
        from sqlalchemy import select

        from agentfox.core.models import Policy
        from agentfox.platform.policy import current_binding

        modes: dict[str, str] = {}
        with self._session() as session:
            for policy in session.scalars(select(Policy).order_by(Policy.key)):
                binding, _ = current_binding(session, policy.id)
                if binding is not None:
                    modes[policy.key] = binding.mode
        return modes

    def set_policy_mode(self, key: str, mode: str) -> None:
        from agentfox.platform.ledger import chain
        from agentfox.platform.policy import set_mode

        with self._session() as session:
            binding = set_mode(session, key, mode)
            if binding is None:
                raise BackendError(f"unknown policy {key}")
            chain.append(
                session,
                f"policy.mode_{mode}",
                actor_type="user",
                actor_id="agentfox up",
                subject_type="policy",
                subject_id=key,
                payload={"mode": mode},
            )

    def submit_scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record the scan the way the gateway's submit route does, so the local
        dashboard shows it with its draft agents and proposed policies."""
        from agentfox.core.models import ScanRun, utcnow
        from agentfox.platform.ledger import chain
        from agentfox.platform.registry.service import propose_from_scan

        with self._session() as session:
            run = ScanRun(
                source_kind="cli",
                repo_full_name=payload.get("label", "repo"),
                status="completed",
                completed_at=utcnow(),
            )
            session.add(run)
            session.flush()
            agents, policies = propose_from_scan(
                session,
                run_id=run.id,
                repo_slug_base=payload.get("label", "repo"),
                repo_display_name=payload.get("label", "repo"),
                frameworks=payload.get("frameworks", []),
                sites=payload.get("sites", []),
                author="agentfox up",
            )
            run.summary_json = {
                "cli_command": "up",
                "files_scanned": payload.get("files_scanned", 0),
                "frameworks": payload.get("frameworks", []),
                "coverage": payload.get("coverage"),
                "sites": payload.get("counts", {}),
                "agents_proposed": agents,
                "policies_proposed": policies,
            }
            session.flush()
            chain.append(
                session,
                "integration.cli.scanned",
                actor_type="user",
                actor_id="agentfox up",
                subject_type="scan_run",
                subject_id=run.id,
                payload=run.summary_json,
            )
            return {"scan_run_id": run.id, "summary": run.summary_json}


# ---------------------------------------------------------------------------
# Remote: a self-hosted gateway or AgentFox Cloud
# ---------------------------------------------------------------------------


class Remote:
    kind = "remote"

    def __init__(self, url: str, token: str, *, client: httpx.Client | None = None) -> None:
        self.where = url.rstrip("/")
        self._client = client or httpx.Client(timeout=15.0)
        self._headers = {"Authorization": f"Bearer {token}"}

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(
                method, f"{self.where}{path}", headers=self._headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise BackendError(f"could not reach {self.where}: {exc}") from exc
        if response.status_code in (401, 403):
            raise BackendError(
                f"{self.where} refused the token ({response.status_code}) — check it is an "
                "API key for this workspace with the owner or admin role"
            )
        return response

    def whoami(self) -> dict[str, Any]:
        response = self._call("GET", "/api/me")
        if response.status_code != 200:
            raise BackendError(f"{self.where}/api/me answered {response.status_code}")
        return response.json()

    def edition(self) -> Edition:
        response = self._call("GET", "/api/version")
        if response.status_code != 200:
            return Edition(name="open-source")
        body = response.json()
        return Edition(
            name=body.get("edition", "open-source"),
            features=frozenset(body.get("features", [])),
            version=body.get("code_version", ""),
        )

    def register_agent(self, slug: str, *, environment: str, framework: str | None) -> None:
        response = self._call(
            "POST",
            "/api/agents",
            json={
                "slug": slug,
                "name": slug,
                "environment": environment,
                "framework": framework,
                "purpose": "registered by agentfox up",
            },
        )
        if response.status_code >= 400:
            raise BackendError(
                f"registering {slug} failed: {response.status_code} {response.text[:200]}"
            )

    def declare_tool(self, key: str, *, impact: str, description: str) -> bool:
        existing = self._call("GET", "/api/tools")
        if existing.status_code == 200 and any(
            t.get("key") == key for t in existing.json().get("tools", [])
        ):
            return False
        response = self._call(
            "POST",
            "/api/tools",
            json={"key": key, "name": key, "impact": impact, "description": description},
        )
        if response.status_code >= 400:
            raise BackendError(
                f"declaring {key} failed: {response.status_code} {response.text[:200]}"
            )
        return True

    def add_monitor(self, kind: str, target: str, *, name: str) -> bool:
        response = self._call(
            "POST", "/api/monitors", json={"kind": kind, "target": target, "name": name}
        )
        if response.status_code == 404:
            raise BackendError("this control plane does not run AgentFox Enterprise monitoring")
        if response.status_code == 409:
            return False
        if response.status_code >= 400:
            raise BackendError(
                f"monitor for {target} failed: {response.status_code} {response.text[:200]}"
            )
        return True

    def register_mcp_server(self, name: str, *, url: str, transport: str) -> None:
        response = self._call(
            "POST", "/api/mcp-servers", json={"name": name, "url": url, "transport": transport}
        )
        if response.status_code >= 400:
            raise BackendError(
                f"registering {name} failed: {response.status_code} {response.text[:200]}"
            )

    def submit_scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._call("POST", "/api/discovery/submit", json=payload)
        if response.status_code >= 400:
            raise BackendError(f"scan upload failed: {response.status_code} {response.text[:200]}")
        return response.json()

    def policy_modes(self) -> dict[str, str]:
        response = self._call("GET", "/api/policies")
        if response.status_code != 200:
            raise BackendError(f"listing policies failed: {response.status_code}")
        return {p["key"]: p["mode"] for p in response.json().get("policies", []) if p.get("mode")}

    def set_policy_mode(self, key: str, mode: str) -> None:
        response = self._call("POST", f"/api/policies/{key}/mode", json={"mode": mode})
        if response.status_code >= 400:
            detail = (
                response.json().get("detail", "")
                if response.headers.get("content-type", "").startswith("application/json")
                else response.text[:200]
            )
            raise BackendError(f"{key} → {mode}: {detail or response.status_code}")
