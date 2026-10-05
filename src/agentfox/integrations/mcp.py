"""I-2 — inline governance of the MCP call path.

Before this, MCP was covered only by *hygiene*: scan a server, snapshot its tools,
raise findings about drift and poisoned descriptions. That catches the server that is
already malicious at scan time and nothing else. The three failures that actually
happen in production all occur at call time:

1. **The rug pull.** A server passes review, an agent is authorised against it, and
   the tool's schema or description changes afterwards. A scan on Monday says nothing
   about the call on Thursday. So the digest in force when the agent was authorised is
   compared against the digest at the moment of the call, and a change blocks.
2. **The undeclared tool.** An agent calls a tool nobody registered. Hygiene scanning
   never sees it because nobody pointed a scan at that server. Here it becomes an
   observed tool and a discovery finding — visible, not invisible.
3. **The poisoned result.** MCP results are the canonical indirect-injection vector
   (Appendix E.1.1): content authored by a third party, arriving as trusted context.
   Results are evaluated on the ``tool_result`` surface and the taint is propagated,
   so an argument later derived from an MCP result cannot exceed the capability
   ceiling for ``tool_result``-sourced data.

The governor is transport-agnostic on purpose. It wraps *any* callable that speaks
list-tools / call-tool, so it works with the official MCP SDK, a hand-rolled client,
or the gateway proxy route — and the ``mcp`` package is never a dependency.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import McpToolSnapshot, Tool, Trace
from agentfox.detection import TaintTracker
from agentfox.prove.findings import raise_finding
from agentfox.registry.service import (
    record_edge,
    scan_mcp_server,
    tool_input_schema,
    upsert_mcp_server,
    upsert_tool,
)
from agentfox.runtime.enforcement import EnforcementResult, Enforcer

log = logging.getLogger(__name__)

#: Tool keys are namespaced by server so two servers exposing `search` stay distinct
#: in the registry, in policy and in the audit trail.
KEY_TEMPLATE = "mcp:{server}/{tool}"

#: MCP verbs that change something. Everything else defaults to read, and an operator
#: can override per tool in the registry — this is a starting classification, not a
#: claim to understand every server's semantics.
_WRITE_HINTS = ("create", "update", "delete", "write", "send", "post", "put", "execute", "run")
_IRREVERSIBLE_HINTS = ("delete", "drop", "purge", "send", "transfer", "deploy", "revoke")


class McpCallBlocked(RuntimeError):
    """Raised when a governed MCP call is refused. Carries the decision."""

    def __init__(self, result: EnforcementResult) -> None:
        super().__init__(result.reason or "MCP call blocked by policy")
        self.result = result


def tool_key(server: str, tool: str) -> str:
    return KEY_TEMPLATE.format(server=server, tool=tool)


def tool_digest(descriptor: dict[str, Any]) -> str:
    """Digest the parts of a tool descriptor that change its meaning.

    Name, description and input schema — the description is included deliberately,
    because tool-poisoning attacks change *only* the description and leave the schema
    identical.
    """
    material = json.dumps(
        {
            "name": descriptor.get("name"),
            "description": descriptor.get("description", ""),
            "inputSchema": descriptor.get("inputSchema", descriptor.get("input_schema", {})),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def infer_impact(name: str, descriptor: dict[str, Any] | None = None) -> str:
    haystack = f"{name} {(descriptor or {}).get('description', '')}".lower()
    if any(h in haystack for h in _IRREVERSIBLE_HINTS):
        return "irreversible"
    if any(h in haystack for h in _WRITE_HINTS):
        return "write"
    return "read"


@dataclass
class McpCallOutcome:
    """The full record of one governed MCP call."""

    tool: str
    server: str
    key: str
    allowed: bool
    result: Any = None
    pre_decision: EnforcementResult | None = None
    post_decision: EnforcementResult | None = None
    drift: dict[str, Any] | None = None
    registered: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "tool": self.tool,
            "key": self.key,
            "allowed": self.allowed,
            "pre": self.pre_decision.to_json() if self.pre_decision else None,
            "post": self.post_decision.to_json() if self.post_decision else None,
            "drift": self.drift,
            "newly_registered": self.registered,
        }


@dataclass
class McpGovernor:
    """Governs one agent's use of one MCP server.

    ``transport`` is any callable ``(tool_name, arguments) -> result``. Keeping the
    transport injected is what lets this govern the official SDK, a hand-rolled
    client and the gateway proxy without importing any of them.
    """

    session: Session
    agent_slug: str
    server_name: str
    transport: Callable[[str, dict[str, Any]], Any] | None = None
    trust_level: str = "untrusted"
    trace: Trace | None = None
    tracker: TaintTracker | None = None
    intent: str | None = None
    credential: str | None = None
    _prior_tools: list[str] = field(default_factory=list)
    #: PL-4: this session's step history (tool, arguments, observation) — the shape
    #: agent_loop.LoopGovernor replays to catch alternating cycles and no-new-
    #: observation runs that per-tool counting (what `_prior_tools` alone drives)
    #: cannot see. `McpGovernor` is the one place with both the prior-call history
    #: and each call's actual post-call observation in the same stateful object
    #: across a session, which is what makes it the real wiring point.
    _prior_steps: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.enforcer = Enforcer(self.session)
        self.server = upsert_mcp_server(
            self.session, self.server_name, trust_level=self.trust_level
        )
        self.tracker = self.tracker or TaintTracker(trace_id=self.trace.id if self.trace else None)

    # -- discovery -------------------------------------------------------

    def register_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Snapshot the listing and register each tool.

        Called on every listing rather than only on a manual scan, because the drift
        that matters is the one that happens between review and use.
        """
        report = scan_mcp_server(self.session, self.server, tools)
        for descriptor in tools:
            name = descriptor.get("name")
            if not name:
                continue
            upsert_tool(
                self.session,
                tool_key(self.server_name, name),
                name=name,
                kind="mcp",
                impact=infer_impact(name, descriptor),
                impact_source="inferred",
                schema=descriptor.get("inputSchema") or descriptor.get("input_schema") or {},
                description=str(descriptor.get("description", "")),
                mcp_server_id=self.server.id,
            )
        return report

    def _descriptor(self, tool: str) -> dict[str, Any] | None:
        snapshot = self.session.scalars(
            select(McpToolSnapshot)
            .where(McpToolSnapshot.mcp_server_id == self.server.id)
            .order_by(McpToolSnapshot.captured_at.desc())
        ).first()
        if snapshot is None:
            return None
        return next((t for t in (snapshot.tools_json or []) if t.get("name") == tool), None)

    def _check_drift(self, key: str, tool: str) -> dict[str, Any] | None:
        """Compare the schema in force now against the one the registry was built on.

        This is the rug pull: the server that passed review on Monday and changed on
        Thursday. A scan cannot catch it; only a check at call time can.
        """
        descriptor = self._descriptor(tool)
        if descriptor is None:
            return None
        registered = self.session.scalar(select(Tool).where(Tool.key == key))
        if registered is None:
            return None
        current = tool_digest(descriptor)
        known = tool_digest(
            {
                "name": registered.name,
                "description": registered.description,
                "inputSchema": tool_input_schema(registered),
            }
        )
        if current == known:
            return None
        return {
            "tool": tool,
            "registered_digest": known,
            "live_digest": current,
            "detail": (
                "the tool's schema or description changed after this agent was "
                "authorised against it"
            ),
        }

    def _register_observed(self, key: str, tool: str) -> bool:
        """An undeclared MCP tool is a discovery finding, never an invisible call."""
        if self.session.scalar(select(Tool).where(Tool.key == key)) is not None:
            return False
        descriptor = self._descriptor(tool) or {}
        upsert_tool(
            self.session,
            key,
            name=tool,
            kind="mcp",
            impact=infer_impact(tool, descriptor),
            impact_source="inferred",
            schema=descriptor.get("inputSchema") or {},
            description=str(descriptor.get("description", "")),
            mcp_server_id=self.server.id,
        )
        raise_finding(
            self.session,
            type="undeclared_mcp_tool",
            severity="high",
            title=f"Agent '{self.agent_slug}' called unregistered MCP tool '{tool}'",
            subject_type="mcp_server",
            subject_id=self.server.id,
            evidence={
                "agent": self.agent_slug,
                "tool": tool,
                "server": self.server_name,
                "key": key,
            },
            control_keys=["NOM-DSC-05", "NOM-IAM-02"],
            fingerprint_parts=(key,),
        )
        self.session.flush()
        return True

    # -- the governed call ----------------------------------------------

    def _blocked(
        self,
        *,
        tool: str,
        key: str,
        registered: bool,
        decision: EnforcementResult,
        drift: dict[str, Any] | None,
        raise_on_block: bool,
    ) -> McpCallOutcome:
        """Build the outcome for a refused call — drift and the pre-flight guard both
        refuse the same way, raising `McpCallBlocked` for a caller that opted in via
        `raise_on_block`, or handing back an `allowed=False` outcome otherwise."""
        outcome = McpCallOutcome(
            tool=tool,
            server=self.server_name,
            key=key,
            allowed=False,
            pre_decision=decision,
            drift=drift,
            registered=registered,
        )
        if raise_on_block:
            raise McpCallBlocked(decision)
        return outcome

    def call(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        provenance: dict[str, str] | None = None,
        transport: Callable[[str, dict[str, Any]], Any] | None = None,
        raise_on_block: bool = False,
    ) -> McpCallOutcome:
        """Govern one MCP tool call, before and after."""
        arguments = arguments or {}
        key = tool_key(self.server_name, tool)
        registered = self._register_observed(key, tool)
        record_edge(
            self.session, "agent", self.agent_slug, "mcp_server", self.server_name, "connects_mcp"
        )

        drift = self._check_drift(key, tool)
        if drift is not None:
            result = self._drift_block(key, tool, drift)
            return self._blocked(
                tool=tool,
                key=key,
                registered=registered,
                decision=result,
                drift=drift,
                raise_on_block=raise_on_block,
            )

        pre = self.enforcer.guard_tool_call(
            agent_slug=self.agent_slug,
            tool_key=key,
            arguments=arguments,
            provenance=provenance,
            intent=self.intent,
            trace=self.trace,
            tracker=self.tracker,
            credential=self.credential,
            prior_tools=list(self._prior_tools),
            prior_steps=list(self._prior_steps),
        )
        if pre.blocked or pre.escalated:
            return self._blocked(
                tool=tool,
                key=key,
                registered=registered,
                decision=pre,
                drift=None,
                raise_on_block=raise_on_block,
            )

        call = transport or self.transport
        if call is None:
            raise ValueError("no transport configured for this governor")
        called_with = pre.taint.get("arguments_snapshot") or arguments
        raw = call(tool, called_with)
        self._prior_tools.append(key)
        self._prior_steps.append({"tool": key, "arguments": called_with, "observation": raw})

        post = self._govern_result(key, tool, raw, arguments)
        content = post.content if post.content is not None else None
        return McpCallOutcome(
            tool=tool,
            server=self.server_name,
            key=key,
            allowed=not post.blocked,
            result=_reproject(raw, content),
            pre_decision=pre,
            post_decision=post,
            registered=registered,
        )

    def _govern_result(
        self, key: str, tool: str, raw: Any, arguments: dict[str, Any] | None = None
    ) -> EnforcementResult:
        """Evaluate what came back, and taint it.

        MCP results are third-party content arriving as trusted context — the textbook
        indirect-injection path. Marking them ``tool_result`` is what stops an argument
        derived from this text reaching a tool whose ceiling forbids it.

        ``arguments`` is the *original call's* arguments, not the result — passing
        ``tool_key`` to `evaluate()` re-runs the capability check as a side effect
        (it needs `tool_impact` either way), and that check reads argument values
        for any constraint the grant declares (``amount < 1000`` and similar). Omitting
        it here meant every constrained capability was re-checked against `{}` and
        denied regardless of the real value — spuriously, and *after* `transport`
        had already run the call's (possibly irreversible) effect, on every governed
        MCP call with an argument-value constraint. Found building a demo target
        with a constrained refund tool; regression test:
        `test_a_call_within_an_argument_constraint_is_not_spuriously_blocked_post_call`.
        """
        text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        agent, identity, _ = self.enforcer.resolve(self.agent_slug, self.credential)
        result = self.enforcer.evaluate(
            agent=agent,
            identity=identity,
            content=text,
            surface="tool_result",
            trace=self.trace,
            taint_source="tool_result",
            tool_key=key,
            arguments=arguments,
            intent=self.intent,
            tracker=self.tracker,
        )
        if self.tracker is not None:
            # Passing the text is what makes propagation work: an argument later
            # derived from this result is recognised as tool_result-tainted rather
            # than arriving as if the agent had authored it.
            self.tracker.mark(f"mcp.{self.server_name}.{tool}", "tool_result", text)
        return result

    def _drift_block(self, key: str, tool: str, drift: dict[str, Any]) -> EnforcementResult:
        raise_finding(
            self.session,
            type="mcp_schema_drift",
            severity="critical",
            title=f"MCP tool '{tool}' changed after authorisation",
            subject_type="mcp_server",
            subject_id=self.server.id,
            evidence={**drift, "agent": self.agent_slug, "server": self.server_name},
            control_keys=["NOM-DSC-05"],
            fingerprint_parts=(key,),
        )
        self.session.flush()
        return EnforcementResult(
            verdict="block",
            effective_verdict="block",
            mode="enforce",
            trace_id=self.trace.id if self.trace else None,
            rules_fired=[
                {
                    "rule_id": "mcp.schema_drift",
                    "effect": "block",
                    "reason": drift["detail"],
                    "severity": "critical",
                    "controls": ["NOM-DSC-05"],
                }
            ],
            reason=drift["detail"],
        )


def _reproject(raw: Any, redacted: str | None) -> Any:
    """Put redacted text back in the shape the caller handed us."""
    if redacted is None:
        return raw
    if isinstance(raw, str):
        return redacted
    try:
        return json.loads(redacted)
    except (ValueError, TypeError):
        return redacted
