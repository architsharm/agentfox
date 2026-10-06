"""Inline governance of the MCP call path.

*Hygiene* alone (scan a server, snapshot its tools, raise findings about drift and
poisoned descriptions) catches the server that is already malicious at scan time
and nothing else. The three failures that actually happen in production all occur
at call time:

1. **The rug pull.** A server passes review, an agent is authorised against it, and
   the tool's schema or description changes afterwards. A scan on Monday says nothing
   about the call on Thursday. So the digest of the tool's registered record — the
   org-wide definition someone reviewed, not a per-grant copy — is compared against
   the server's current listing at the moment of the call, and a change blocks. So
   does a tool the server stops listing, since what it would run can no longer be
   compared. Accepting a changed definition lifts the block; that is a loosening, so
   it is a change proposal (kind ``mcp.tool.accept``) with the two-person rule for
   org-level loosenings, and every step is in the audit chain.
2. **The undeclared tool.** An agent calls a tool nobody registered. Hygiene scanning
   never sees it because nobody pointed a scan at that server. Here it becomes an
   observed tool and a discovery finding — visible, not invisible.
3. **The poisoned result.** MCP results are the canonical indirect-injection vector:
   content authored by a third party, arriving as trusted context.
   Results are evaluated on the ``tool_result`` surface and the taint is propagated,
   so an argument later derived from an MCP result cannot exceed the capability
   ceiling for ``tool_result``-sourced data.

The governor is transport-agnostic on purpose. It wraps *any* callable that speaks
list-tools / call-tool, so it works with the official MCP SDK, a hand-rolled client,
or the gateway proxy route — and the ``mcp`` package is never a dependency.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Capability, Decision, Identity, McpToolSnapshot, Tool, Trace
from agentfox.detection import TaintTracker
from agentfox.errors import AgentFoxError
from agentfox.prove.findings import raise_finding
from agentfox.registry.service import (
    normalise_tool_list,
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


class McpCallBlocked(AgentFoxError, RuntimeError):
    """Raised when a governed MCP call is refused. Carries the decision.

    An `agentfox.errors.AgentFoxError` like every other refusal, and still a
    ``RuntimeError`` so ``except RuntimeError`` keeps catching it.
    """

    def __init__(self, result: EnforcementResult) -> None:
        super().__init__(result.reason or "MCP call blocked by policy")
        self.result = result


def tool_key(server: str, tool: str) -> str:
    return KEY_TEMPLATE.format(server=server, tool=tool)


#: The MCP tool annotations that describe what a call does to the world. A client that
#: auto-approves read-only tools reads exactly these, so a change to one is held like a
#: change to the description. `title` and `outputSchema` are not pinned: the title is a
#: display label, and the result is evaluated and tainted as ``tool_result`` whatever
#: shape it claims. A change to either still raises a ``schema_drift`` finding.
IMPACT_ANNOTATIONS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def impact_annotations(descriptor: dict[str, Any]) -> dict[str, Any]:
    annotations = descriptor.get("annotations") or {}
    if not isinstance(annotations, dict):
        return {}
    return {k: annotations[k] for k in IMPACT_ANNOTATIONS if k in annotations}


def tool_digest(descriptor: dict[str, Any], *, annotations: bool = True) -> str:
    """Digest the parts of a tool descriptor that change its meaning.

    Name, description, input schema and the impact annotations — the description is
    included deliberately, because tool-poisoning attacks change *only* the
    description and leave the schema identical. Annotations enter the material only
    when there are some, so a tool without them digests as it always did.
    ``annotations=False`` compares against a record made before they were kept.
    """
    material: dict[str, Any] = {
        "name": descriptor.get("name"),
        "description": descriptor.get("description", ""),
        "inputSchema": descriptor.get("inputSchema", descriptor.get("input_schema", {})),
    }
    hints = impact_annotations(descriptor) if annotations else {}
    if hints:
        material["annotations"] = hints
    encoded = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()[:32]


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
    #: This session's step history (tool, arguments, observation) — the shape
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

    def register_tools(
        self,
        tools: list[dict[str, Any]],
        *,
        accept_changes: bool = False,
        actor: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Snapshot the listing and register each tool.

        Called on every listing rather than only on a manual scan, because the drift
        that matters is the one that happens between review and use.

        A tool registered for the first time is recorded as listed. A tool that is
        already registered from an earlier listing and now lists *differently* is
        **held**: the snapshot records the new listing (so the change is a
        ``schema_drift`` finding and calls are refused with ``mcp.schema_drift``),
        but the registered record — the reviewed one — is left as it was, and an
        ``mcp.tool.accept`` change proposal is filed for the new definition.

        Accepting it lifts the block, so it is a loosening of an org-wide record and
        takes two different people, like any other (``contract.
        requires_second_approver``). ``accept_changes=True`` with ``actor`` is that
        person's approval of each held tool's proposal; the change applies when the
        second person approves, here or through the proposals routes. Without a named
        actor nothing is accepted: an agent that hands its own listing back cannot
        approve it.

        A tool the server adds to a listing it has sent before is registered, and if
        an existing wildcard grant already covers it, a ``mcp_tool_added_under_wildcard``
        finding names the grants — the grant was made before anyone saw this tool.
        """
        if accept_changes and not (actor or "").strip():
            raise ValueError(
                "accepting a changed listing needs an actor: the person who reviewed it"
            )
        tools = normalise_tool_list(tools)
        listed_before = self._latest_snapshot() is not None
        report = scan_mcp_server(self.session, self.server, tools)
        held: list[str] = []
        accepted: list[str] = []
        awaiting: list[str] = []
        proposals: dict[str, str] = {}
        added: list[str] = []
        for descriptor in tools:
            name = descriptor.get("name")
            if not name:
                continue
            key = tool_key(self.server_name, name)
            existing = self.session.scalar(select(Tool).where(Tool.key == key))
            pinned = _registered_digest(existing) if existing is not None else None
            if pinned is not None and pinned != _live_digest(descriptor, existing):
                proposal = self._propose_acceptance(key, descriptor, pinned, report)
                proposals[name] = proposal.id
                if accept_changes:
                    self._accept(proposal, actor=str(actor), note=note)
                    if proposal.status == "applied":
                        accepted.append(name)
                        continue
                    if proposal.decided_by and proposal.status != "approved":
                        awaiting.append(name)
                held.append(name)
                continue
            if existing is None and listed_before:
                added.append(name)
            upsert_tool(
                self.session,
                key,
                name=name,
                kind="mcp",
                impact=infer_impact(name, descriptor),
                impact_source="inferred",
                schema=descriptor.get("inputSchema") or descriptor.get("input_schema") or {},
                description=str(descriptor.get("description", "")),
                mcp_server_id=self.server.id,
                annotations=impact_annotations(descriptor),
            )
        if held:
            log.warning(
                "MCP server '%s' listed changed tools %s; the registered listing stays in "
                "force and calls are refused until the change is accepted",
                self.server_name,
                held,
            )
        report["held"] = held
        report["accepted"] = accepted
        report["awaiting_second_approver"] = awaiting
        report["proposals"] = proposals
        report["added_under_wildcard"] = [n for n in added if self._flag_wildcard_addition(n)]
        return report

    def _propose_acceptance(
        self, key: str, descriptor: dict[str, Any], pinned: str, report: dict[str, Any]
    ):
        """File (or refresh) the proposal to accept a held tool's new definition."""
        from agentfox.improvement import contract
        from agentfox.improvement.proposals import attach_proof, file_proposal

        name = str(descriptor["name"])
        live = tool_digest(descriptor)
        after = {
            "description": str(descriptor.get("description", "")),
            "inputSchema": descriptor.get("inputSchema") or descriptor.get("input_schema") or {},
            "annotations": impact_annotations(descriptor),
        }
        poisoning = [
            i
            for i in report.get("issues", [])
            if i.get("type") == "tool_poisoning" and i.get("tool") == name
        ]
        proposal = file_proposal(
            self.session,
            kind="mcp.tool.accept",
            source="mcp.listing",
            target_type="tool",
            target_ref=key,
            scope_level="org",
            scope_id="*",
            title=f"Accept the changed definition of MCP tool '{name}' on '{self.server_name}'",
            rationale=(
                "The server now lists this tool differently from the reviewed definition, "
                "and calls to it are refused until the new definition is accepted."
            ),
            direction=contract.LOOSENS,
            diff={
                "tool_key": key,
                "server": self.server_name,
                "name": name,
                **after,
                "from_digest": pinned,
                "to_digest": live,
            },
            evidence={"poisoning": poisoning},
            fingerprint=f"mcp.tool.accept:{key}:{live}",
        )
        if proposal.status == "proposed":
            # Nothing to replay: the evidence a reviewer needs is the two definitions.
            registered = self.session.scalar(select(Tool).where(Tool.key == key))
            attach_proof(
                self.session,
                proposal,
                {
                    "before": {
                        "description": registered.description,
                        "inputSchema": tool_input_schema(registered),
                        "annotations": registered.annotations_json,
                    },
                    "after": after,
                    "poisoning_patterns": [p for i in poisoning for p in i.get("patterns", [])],
                },
                passed=True,
            )
        return proposal

    def _accept(self, proposal, *, actor: str, note: str | None) -> None:
        """One person's approval of a held tool's proposal, applied once it has two."""
        from agentfox.improvement.proposals import apply_proposal, decide

        if proposal.status == "proven":
            decide(
                self.session,
                proposal,
                approve=True,
                actor=actor,
                note=note or "accepted the changed MCP listing",
            )
        if proposal.status == "approved":
            apply_proposal(self.session, proposal, actor=actor, automated=False)

    def _flag_wildcard_addition(self, name: str) -> bool:
        """A tool the server added later, already covered by a wildcard grant."""
        key = tool_key(self.server_name, name)
        grants = [
            c
            for c in self.session.scalars(select(Capability).where(Capability.tool_key != key))
            if any(ch in c.tool_key for ch in "*?[") and fnmatch.fnmatch(key, c.tool_key)
        ]
        if not grants:
            return False
        raise_finding(
            self.session,
            type="mcp_tool_added_under_wildcard",
            severity="high",
            title=(
                f"MCP server '{self.server_name}' added tool '{name}', which a wildcard "
                "grant already allows"
            ),
            subject_type="mcp_server",
            subject_id=self.server.id,
            evidence={
                "tool": name,
                "server": self.server_name,
                "key": key,
                "grants": [
                    {
                        "capability_id": c.id,
                        "principal": getattr(
                            self.session.get(Identity, c.identity_id), "principal", None
                        ),
                        "pattern": c.tool_key,
                    }
                    for c in grants
                ],
            },
            control_keys=["NOM-DSC-05", "NOM-IAM-02"],
            fingerprint_parts=(key,),
        )
        return True

    def _latest_snapshot(self) -> McpToolSnapshot | None:
        return self.session.scalars(
            select(McpToolSnapshot)
            .where(McpToolSnapshot.mcp_server_id == self.server.id)
            .order_by(McpToolSnapshot.captured_at.desc())
        ).first()

    def _descriptor(self, tool: str) -> dict[str, Any] | None:
        snapshot = self._latest_snapshot()
        if snapshot is None:
            return None
        return next((t for t in (snapshot.tools_json or []) if t.get("name") == tool), None)

    def _listed_before(self, tool: str) -> bool:
        """Whether any listing this server sent has included the tool."""
        return any(
            t.get("name") == tool
            for snapshot in self.session.scalars(
                select(McpToolSnapshot).where(McpToolSnapshot.mcp_server_id == self.server.id)
            )
            for t in (snapshot.tools_json or [])
        )

    def _check_drift(self, key: str, tool: str) -> dict[str, Any] | None:
        """Compare the schema in force now against the one the registry was built on.

        This is the rug pull: the server that passed review on Monday and changed on
        Thursday. A scan cannot catch it; only a check at call time can.
        """
        registered = self.session.scalar(select(Tool).where(Tool.key == key))
        if registered is None:
            return None
        descriptor = self._descriptor(tool)
        if descriptor is None:
            # A tool the server listed before and has now dropped. Its current
            # definition cannot be compared with the reviewed one, and skipping the
            # check here let a changed tool through by being left out of the next
            # listing. A tool that was never listed is not pinned by any listing.
            known = _registered_digest(registered)
            if known is None or not self._listed_before(tool):
                return None
            return {
                "tool": tool,
                "registered_digest": known,
                "live_digest": None,
                "detail": (
                    "the tool is no longer in the server's listing, so what the server "
                    "would run cannot be compared with the reviewed definition"
                ),
            }
        current = _live_digest(descriptor, registered)
        known = _tool_record_digest(registered)
        if current == known:
            return None
        return {
            "tool": tool,
            "registered_digest": known,
            "live_digest": current,
            "detail": (
                "the tool's description, schema or impact annotations changed since its "
                "definition was reviewed"
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
            result = self._drift_block(key, tool, drift, arguments)
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
        for any constraint the grant declares (``amount < 1000`` and similar). Without
        them every constrained capability would be re-checked against `{}` and denied
        regardless of the real value — spuriously, and *after* `transport` has already
        run the call's (possibly irreversible) effect.
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

    def _drift_block(
        self, key: str, tool: str, drift: dict[str, Any], arguments: dict[str, Any]
    ) -> EnforcementResult:
        raise_finding(
            self.session,
            type="mcp_schema_drift",
            severity="critical",
            title=f"MCP tool '{tool}' changed since its definition was reviewed",
            subject_type="mcp_server",
            subject_id=self.server.id,
            evidence={**drift, "agent": self.agent_slug, "server": self.server_name},
            control_keys=["NOM-DSC-05"],
            fingerprint_parts=(key,),
        )
        rules_fired = [
            {
                "rule_id": "mcp.schema_drift",
                "effect": "block",
                "reason": drift["detail"],
                "severity": "critical",
                "controls": ["NOM-DSC-05"],
            }
        ]
        # Recorded like any other tool-call decision, so the refusal is in the
        # decision history, counted by reports, and replayable by `simulate` (which
        # keeps rules a candidate policy does not replace) — not only a finding.
        agent, identity, _ = self.enforcer.resolve(self.agent_slug, self.credential)
        registered = self.session.scalar(select(Tool).where(Tool.key == key))
        row = Decision(
            trace_id=self.trace.id if self.trace else None,
            agent_id=agent.id if agent else None,
            identity_id=identity.id if identity else None,
            surface="tool_args",
            tool_key=key,
            verdict="block",
            rules_fired_json=rules_fired,
            taint_summary_json={
                "arguments_snapshot": dict(arguments),
                "tool_impact": registered.impact if registered else "read",
                "mcp_drift": drift,
            },
            mode="enforce",
        )
        self.session.add(row)
        self.session.flush()
        self.enforcer._raise_trace_verdict(self.trace, "block")
        return EnforcementResult(
            verdict="block",
            effective_verdict="block",
            mode="enforce",
            decision_id=row.id,
            trace_id=self.trace.id if self.trace else None,
            rules_fired=rules_fired,
            reason=drift["detail"],
        )


def _tool_record_digest(tool: Tool) -> str:
    """The digest of a registered tool, in the same terms as `tool_digest`."""
    return tool_digest(
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool_input_schema(tool),
            "annotations": tool.annotations_json or {},
        }
    )


#: Public name for the appliers, which compare a record against a proposal's digests.
record_digest = _tool_record_digest


def _live_digest(descriptor: dict[str, Any], record: Tool) -> str:
    """The listed definition's digest, in the terms the record was pinned in.

    A record written before annotations were kept has none to compare, so the
    listing is digested without them; the next unchanged listing records them.
    """
    return tool_digest(descriptor, annotations=record.annotations_json is not None)


def _registered_digest(tool: Tool) -> str | None:
    """The digest a registered tool is pinned to, or None if nothing pins it.

    A record with neither a description nor an input schema was never registered
    from a listing — it was declared by key, or observed being called before any
    listing arrived — so there is no reviewed content for a new listing to differ
    from, and the first listing is recorded as a first registration.
    """
    if not (tool.description or tool_input_schema(tool)):
        return None
    return _tool_record_digest(tool)


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
