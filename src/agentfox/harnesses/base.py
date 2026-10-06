"""The harness adapter interface: what every coding agent AgentFox governs must provide.

A harness is a coding agent that calls a hook around its own actions (Claude Code
today). Each one speaks its own dialect of the same contract — JSON on stdin, a reply on
stdout, an exit code — with its own event names, field names, tool names and failure
behaviour. An adapter translates that dialect into the vocabulary here and back, and
declares, per event, what a reply can actually do there.

The vocabulary:

* :class:`AgentEvent` — one hook invocation, in our terms. ``kind`` is canonical
  (:data:`EVENT_KINDS`); ``event`` keeps the harness's own name, because the reply
  shape is chosen by it.
* :class:`Decision` — what AgentFox wants done: allow, deny, ask, modify or context.
* :class:`EventCaps` — what the harness lets a hook do on one event. A decision the
  harness cannot honour is **downgraded on purpose** by :func:`downgrade`, and the
  downgrade is recorded on the decision that was applied (``downgraded_from``), never
  passed off as the decision that was asked for.
* :class:`HookOutput` — what the hook process prints and exits with.

The interface does not change what is enforced. The daemon still evaluates the
harness's own tool name (``Bash``), because that is what the registry and every grant
are keyed on; the canonical name (``shell``) rides alongside for policies and reports
that want to be harness-neutral.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentfox.capabilities.discovery.sessions import SessionScanReport

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: The moments a harness can call a hook, in canonical names.
EventKind = Literal[
    "session.start",
    "prompt.submit",
    "tool.pre",
    "tool.post",
    "tool.error",
    "permission.request",
    "stop",
]
EVENT_KINDS: tuple[str, ...] = (
    "session.start",
    "prompt.submit",
    "tool.pre",
    "tool.post",
    "tool.error",
    "permission.request",
    "stop",
)

#: What each event is a checkpoint *on*. A hook event is a moment, not a surface, and
#: this mapping is the thing a reader gets wrong: ``tool.pre`` sees arguments about to
#: be used, ``tool.post`` a result arriving (the canonical indirect-injection vector),
#: ``prompt.submit`` the operator's own words. Anything else is read as ``input``.
KIND_SURFACE: dict[str, str] = {
    "tool.pre": "tool_args",
    "tool.post": "tool_result",
    "prompt.submit": "input",
}

#: Canonical tool names. A harness's own name maps onto one of these, or onto
#: ``mcp:<server>/<tool>``; a tool with no canonical meaning keeps ``native:<name>``.
CanonicalTool = str
CANONICAL_TOOLS: tuple[str, ...] = (
    "shell",
    "shell.output",
    "shell.kill",
    "file.read",
    "file.write",
    "file.edit",
    "file.search",
    "notebook.edit",
    "web.fetch",
    "web.search",
    "agent.spawn",
)

Maturity = Literal["stable", "incubating", "sandbox"]
Scope = Literal["project", "local", "user"]
DecisionKind = Literal["allow", "deny", "ask", "modify", "context"]

#: How a capability row was established. Ordered weakest to strongest.
Evidence = Literal["VENDOR_DOCS", "SOURCE", "LIVE_PROBE"]

#: Verdicts that mean "do not let this happen". `escalate` is included because at a
#: hook there is nobody to escalate *to*: the agent is mid-call and the operator is not
#: watching a queue. Refusing with the reason is the honest rendering of "a human must
#: decide", and it is what the agent can act on.
REFUSING = frozenset({"block", "escalate", "abstain"})


@dataclass(frozen=True)
class Verified:
    """One thing established about a harness event, with how and against what version.

    **Absent means unverified, not "block".** A version is part of the claim: a row
    whose version has moved is due for a re-probe, not evidence.
    """

    capability: Literal["block", "observe"]
    evidence: Evidence
    #: The harness version this was established against.
    version: str
    #: Where to look to check it again — a file and symbol, a docs URL, or the probe.
    reference: str
    note: str = ""


@dataclass(frozen=True)
class EventCaps:
    """What a hook reply can do on one event of one harness."""

    #: A refusal stops the action (the call, or the turn).
    can_block: bool = False
    #: The reply can rewrite the tool call's arguments.
    can_modify: bool = False
    #: The reply can hand the decision to the person at the keyboard.
    can_ask: bool = False
    #: The reply can put text in front of the model.
    can_inject_context: bool = False
    #: A hook that does not answer in time lets the action through.
    fails_open_on_timeout: bool = True
    #: The evidence behind ``can_block``; ``None`` means nobody has checked.
    verified: Verified | None = None
    #: The evidence behind ``can_modify``, recorded separately because rewriting is a
    #: different claim from blocking.
    rewrite_verified: Verified | None = None


@dataclass(frozen=True)
class AgentEvent:
    """What the harness told us, in our vocabulary."""

    harness: str
    #: The harness's own event name (``PreToolUse``); the reply shape follows it.
    event: str
    #: The canonical event kind, or ``""`` for an event the adapter does not map.
    kind: str
    #: The harness's own tool name — what the registry and grants are keyed on.
    tool: str
    arguments: dict[str, Any]
    #: The harness-neutral name for ``tool`` (``shell``, ``mcp:github/create_issue``).
    canonical_tool: str = ""
    session_id: str = ""
    cwd: str = ""
    #: The harness's own permission mode, recorded because a deny means something
    #: different in a session already running with checks bypassed.
    permission_mode: str = ""
    #: Free text this event carries, where it carries any: a tool's result, or the
    #: operator's own turn. Empty on a tool call, whose payload is the arguments.
    content: str = ""

    @property
    def surface(self) -> str:
        """Which of the engine's surfaces this event is a checkpoint on."""
        return KIND_SURFACE.get(self.kind, "input")

    @property
    def checks_content(self) -> bool:
        """True where the thing to check is text rather than a call."""
        return self.surface in {"tool_result", "input"}


@dataclass(frozen=True)
class Decision:
    """What AgentFox wants done with one event.

    ``downgraded_from`` is set only on a decision produced by :func:`downgrade`: it
    names the decision that was asked for and could not be honoured here, and
    ``downgrade_note`` says why.
    """

    kind: DecisionKind
    reason: str = ""
    rules: tuple[str, ...] = ()
    #: The replacement arguments, for ``modify``.
    arguments: dict[str, Any] | None = None
    #: Text for the model, for ``context``.
    context: str = ""
    downgraded_from: DecisionKind | None = None
    downgrade_note: str = ""

    @classmethod
    def allow(cls) -> Decision:
        return cls("allow")

    @classmethod
    def deny(cls, reason: str = "", rules: Iterable[str] = ()) -> Decision:
        return cls("deny", reason=reason, rules=tuple(r for r in rules if r))

    @classmethod
    def ask(cls, reason: str = "", rules: Iterable[str] = ()) -> Decision:
        return cls("ask", reason=reason, rules=tuple(r for r in rules if r))

    @classmethod
    def modify(cls, arguments: dict[str, Any], reason: str = "") -> Decision:
        return cls("modify", reason=reason, arguments=dict(arguments))

    @classmethod
    def with_context(cls, text: str) -> Decision:
        return cls("context", context=text)

    @property
    def downgraded(self) -> bool:
        return self.downgraded_from is not None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.reason:
            out["reason"] = self.reason
        if self.rules:
            out["rules"] = list(self.rules)
        if self.arguments is not None:
            out["arguments"] = self.arguments
        if self.context:
            out["context"] = self.context
        if self.downgraded_from:
            out["downgraded_from"] = self.downgraded_from
            out["downgrade_note"] = self.downgrade_note
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Decision:
        return cls(
            kind=data["kind"],
            reason=str(data.get("reason") or ""),
            rules=tuple(data.get("rules") or ()),
            arguments=data.get("arguments"),
            context=str(data.get("context") or ""),
        )


@dataclass(frozen=True)
class HookOutput:
    """What the hook process does: print ``stdout``, print ``stderr``, exit."""

    stdout: str
    stderr: str = ""
    exit_code: int = 0
    #: The decision as applied, after any downgrade.
    decision: Decision = field(default_factory=Decision.allow)

    @property
    def body(self) -> dict[str, Any]:
        """``stdout`` as the JSON object it is (``{}`` when empty)."""
        return json.loads(self.stdout) if self.stdout.strip() else {}


@dataclass(frozen=True)
class FileChange:
    """One file ``install`` writes or would write."""

    path: Path
    #: The whole new content of the file.
    content: str
    #: ``create``, ``update``, or ``unchanged`` (already installed; nothing to write).
    action: Literal["create", "update", "unchanged"]
    #: The harness events this change adds hooks for.
    events: tuple[str, ...] = ()

    def apply(self) -> None:
        if self.action == "unchanged":
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.content)


class InstallError(ValueError):
    """An existing settings file that ``install`` will not overwrite."""


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class HarnessAdapter(Protocol):
    """A coding agent AgentFox governs through its hooks."""

    #: The name ``agentfox hooks run --harness <name>`` is called with.
    name: str
    #: The product name, for people.
    display_name: str
    maturity: Maturity
    #: Per canonical event kind, what a reply can do there.
    capabilities: Mapping[str, EventCaps]
    #: The harness's own event names, canonical kind -> native name.
    events: Mapping[str, str]
    #: Native tool name -> canonical name.
    tool_map: Mapping[str, CanonicalTool]
    #: Native tool name -> declared impact (``read`` … ``irreversible``): the harness's
    #: built-in tools, which ``install`` declares and grants.
    tool_impacts: Mapping[str, str]

    def canonical_tool(self, native: str) -> CanonicalTool: ...

    def parse(self, raw: Mapping[str, Any]) -> AgentEvent: ...

    def render(self, decision: Decision, event: AgentEvent) -> HookOutput: ...

    def install(self, root: Path, scope: Scope, *, agent: str) -> list[FileChange]: ...

    def hooked_agents(self, root: Path) -> list[str]: ...

    def mcp_config_paths(self, root: Path) -> list[Path]: ...

    def transcripts(self, base: Path | None = None) -> SessionScanReport | None: ...


# ---------------------------------------------------------------------------
# Helpers every adapter shares
# ---------------------------------------------------------------------------


def downgrade(decision: Decision, caps: EventCaps | None) -> Decision:
    """The strongest decision this event can honour, recording any step down.

    * ``modify`` the harness cannot apply becomes ``deny``: running the unrewritten
      call is the one outcome the rewrite existed to prevent.
    * ``ask`` the harness cannot put to a person becomes ``deny``, for the same reason
      an escalation does at a hook: nobody is watching a queue.
    * ``deny`` on an event that cannot block becomes ``context`` (the reason reaches the
      model, the action has already happened), or ``allow`` if even that is not possible.
    * ``context`` the harness cannot inject becomes ``allow``.

    Each step keeps the original reason and rules, and the result carries
    ``downgraded_from`` naming what was asked for.
    """
    caps = caps or EventCaps()
    original = decision.downgraded_from or decision.kind
    current = decision
    notes: list[str] = [decision.downgrade_note] if decision.downgrade_note else []

    def step(kind: DecisionKind, note: str) -> Decision:
        notes.append(note)
        return replace(
            current,
            kind=kind,
            arguments=None if kind != "modify" else current.arguments,
            downgraded_from=original,
            downgrade_note="; ".join(notes),
        )

    if current.kind == "modify" and not caps.can_modify:
        current = step("deny", "this event cannot rewrite a call, so it is refused instead")
    if current.kind == "ask" and not caps.can_ask:
        current = step("deny", "this event cannot ask a person, so it is refused instead")
    if current.kind == "deny" and not caps.can_block:
        if caps.can_inject_context:
            current = step(
                "context", "this event cannot stop the action; the reason is shown to the model"
            )
        else:
            current = step("allow", "this event can neither stop the action nor tell the model")
    if current.kind == "context" and not caps.can_inject_context:
        current = step("allow", "this event cannot put text in front of the model")
    return current


def decision_from_verdict(verdict: Mapping[str, Any], event: AgentEvent) -> Decision:
    """The daemon's verdict reply as a :class:`Decision`.

    Refusing verdicts (:data:`REFUSING`) deny with the reason and the rules that fired.
    ``rewrittenArguments`` that differ from the call's own become ``modify``, on a tool
    call only. Everything else allows.
    """
    name = str(verdict.get("verdict") or "allow")
    reason = str(verdict.get("reason") or "")
    rules = [str(r) for r in (verdict.get("rules") or []) if r]
    if name in REFUSING:
        return Decision.deny(reason, rules)
    rewritten = verdict.get("rewrittenArguments")
    if (
        event.kind == "tool.pre"
        and isinstance(rewritten, dict)
        and rewritten
        and rewritten != event.arguments
    ):
        return Decision.modify(rewritten, reason)
    return Decision.allow()


def refusal_text(decision: Decision, fallback: str) -> str:
    """``AgentFox: <reason> (<rules>)`` — what an agent reads when it is refused.

    Named rules rather than "blocked by policy": the agent is the one that has to do
    something else next, so it needs to know what it tripped.
    """
    detail = f" ({', '.join(decision.rules)})" if decision.rules else ""
    return f"AgentFox: {decision.reason or fallback}{detail}"


def hook_command(harness: str, agent: str) -> str:
    """The command ``install`` writes into a harness's hook configuration."""
    return f"agentfox hooks run --harness {harness} --agent {agent}"


#: Reads :func:`hook_command` back out of a settings file: the ``--agent`` it names.
HOOK_COMMAND_RE = re.compile(r"agentfox hooks run\b[^\"\n]*?--agent[ =]([A-Za-z0-9_.:@/-]+)")


def agents_in_hook_commands(text: str) -> set[str]:
    """Every agent slug an ``agentfox hooks run`` command in ``text`` governs."""
    return set(HOOK_COMMAND_RE.findall(text))


__all__ = [
    "CANONICAL_TOOLS",
    "EVENT_KINDS",
    "HOOK_COMMAND_RE",
    "KIND_SURFACE",
    "REFUSING",
    "AgentEvent",
    "CanonicalTool",
    "Decision",
    "DecisionKind",
    "EventCaps",
    "EventKind",
    "Evidence",
    "FileChange",
    "HarnessAdapter",
    "HookOutput",
    "InstallError",
    "Maturity",
    "Scope",
    "Verified",
    "agents_in_hook_commands",
    "decision_from_verdict",
    "downgrade",
    "hook_command",
    "refusal_text",
]
