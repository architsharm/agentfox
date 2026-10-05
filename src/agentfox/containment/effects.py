"""F3 — effects that outlive the call: retries, rollback and cascades.

Action analysis governs *what a statement will do*. This governs what happens to the
effect afterwards, which is a different axis and the one that produces the expensive
incidents:

* the same refund issued twice because the transport retried,
* a three-step transfer that failed on step three and left steps one and two standing,
* one webhook that turned a single update into four hundred downstream writes.

None of these is a bad decision. Every individual call was authorised, well-formed and
correct; the failure is in the *arrangement*, and no per-call check can see it.

The unifying idea is that an effectful call has to be describable before it is made:
what identifies it, what undoes it, and what else it sets off. A system that cannot
answer those three questions cannot retry safely, cannot roll back, and cannot bound
its own blast radius — and it will need all three, because at-least-once delivery is
the default everywhere and a partial failure is not an edge case.

The strongest position taken here is that **an effectful call with no idempotency key
is itself the finding**, not merely a duplicate that happens to be detected. A
duplicate is evidence the gap was already exploited; the missing key is the gap. Most
systems only ever notice the former.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from agentfox.core.finding import RiskFinding

# --- Idempotency (F3.7) ----------------------------------------------------

#: Argument names that vary between attempts of the same logical operation. Including
#: them in the key makes every retry look new, which is the failure this exists to
#: prevent — so the default list is generous and the caller can extend it.
VOLATILE_ARGS = (
    "timestamp",
    "time",
    "now",
    "requested_at",
    "created_at",
    "sent_at",
    "request_id",
    "trace_id",
    "span_id",
    "correlation_id",
    "message_id",
    "nonce",
    "attempt",
    "retry",
    "retry_count",
    "idempotency_key",
    "client_token",
    "session_id",
    "user_agent",
    "ip",
    "signature",
)

#: Tools whose effects are visible outside the system. A duplicate here cannot be
#: cleaned up quietly.
_EXTERNAL_HINTS = (
    "payment",
    "refund",
    "transfer",
    "charge",
    "email",
    "sms",
    "notify",
    "publish",
    "webhook",
    "ship",
    "order",
    "invoice",
    "provision",
)


def _canonical(value: Any) -> Any:
    """A stable shape for hashing.

    Dict ordering and float formatting both vary between attempts without the
    operation changing, and either one silently defeats the key.
    """
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def idempotency_key(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    ignore: tuple[str, ...] = VOLATILE_ARGS,
    scope: str = "",
) -> str:
    """Derive a key that is stable across retries of the same logical operation.

    Volatile arguments are excluded by name. This is a heuristic and it is stated as
    one: a caller-supplied key is always better, because only the caller knows whether
    two identical-looking refunds are a retry or a customer who was charged twice. The
    derived key exists so that a system which supplies no key still gets *some*
    protection, not so that supplying one becomes optional.
    """
    significant = {
        k: _canonical(v)
        for k, v in sorted((arguments or {}).items())
        if k.lower() not in {i.lower() for i in ignore}
    }
    payload = json.dumps(
        {"scope": scope, "tool": tool, "arguments": significant},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def is_external(tool: str) -> bool:
    lowered = tool.lower()
    return any(hint in lowered for hint in _EXTERNAL_HINTS)


ReplayFinding = RiskFinding


@dataclass
class _Entry:
    key: str
    tool: str
    at: dt.datetime
    result: Any = None


class EffectLedger:
    """Remembers which effectful calls have already happened.

    In-process and bounded by a time window, which is the right shape for the decision
    being made: "have I just done this?" is a question about recent history, and a
    ledger that grows without bound to answer it is a memory leak wearing a hat. A
    durable implementation belongs behind the same interface — the window is the
    semantics, not an implementation limit.
    """

    def __init__(self, *, window_seconds: int = 900) -> None:
        self.window = dt.timedelta(seconds=window_seconds)
        self._entries: dict[str, _Entry] = {}

    def _expire(self, now: dt.datetime) -> None:
        cutoff = now - self.window
        for key in [k for k, e in self._entries.items() if e.at < cutoff]:
            del self._entries[key]

    def check(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        key: str | None = None,
        effectful: bool = True,
        now: dt.datetime | None = None,
    ) -> list[ReplayFinding]:
        """What is wrong with making this call right now.

        Two findings, and the second is the one worth having. A repeat of a key already
        seen is a duplicate execution. A call with no caller-supplied key is a duplicate
        *waiting* to happen, and it is reported even on the first attempt — the retry is
        not a possibility to be managed, it is a certainty to be prepared for.
        """
        now = now or dt.datetime.now(dt.UTC)
        self._expire(now)
        findings: list[ReplayFinding] = []
        if not effectful:
            return findings

        derived = key or idempotency_key(tool, arguments)
        if key is None:
            findings.append(
                ReplayFinding(
                    "no-idempotency-key",
                    f"'{tool}' has an external effect and carries no caller-supplied "
                    "idempotency key, so a transport retry cannot be distinguished from a "
                    "second genuine request",
                    "high" if is_external(tool) else "medium",
                    {"tool": tool, "derived_key": derived},
                )
            )

        if (previous := self._entries.get(derived)) is not None:
            age = (now - previous.at).total_seconds()
            findings.append(
                ReplayFinding(
                    "duplicate-execution",
                    f"'{tool}' with these arguments already executed {age:.0f}s ago",
                    "critical" if is_external(tool) else "high",
                    {"tool": tool, "key": derived, "seconds_ago": round(age, 1)},
                )
            )
        return findings

    def record(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        key: str | None = None,
        result: Any = None,
        now: dt.datetime | None = None,
    ) -> str:
        now = now or dt.datetime.now(dt.UTC)
        derived = key or idempotency_key(tool, arguments)
        self._entries[derived] = _Entry(derived, tool, now, result)
        return derived

    def replay(self, key: str) -> Any:
        entry = self._entries.get(key)
        return entry.result if entry else None


# --- Compensation (F3.10) --------------------------------------------------


@dataclass
class Step:
    """One effectful step in a multi-step operation."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    #: The tool that undoes this step. None means there is no way back.
    compensator: str | None = None
    #: Set when the effect leaves the system entirely — a sent email, a posted payment.
    #: An irreversible step is not the same as one that merely lacks a compensator: a
    #: compensator could be written for the second and never for the first.
    irreversible: bool = False

    @property
    def recoverable(self) -> bool:
        return bool(self.compensator) and not self.irreversible


@dataclass
class Plan:
    """How to unwind a sequence that stopped part-way."""

    compensations: list[Step] = field(default_factory=list)
    unrecoverable: list[Step] = field(default_factory=list)
    findings: list[ReplayFinding] = field(default_factory=list)
    ordering_hint: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unrecoverable

    @property
    def verdict(self) -> str:
        if any(f.severity == "critical" for f in self.findings):
            return "block"
        return "escalate" if self.findings else "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "verdict": self.verdict,
            "compensations": [s.tool for s in self.compensations],
            "unrecoverable": [s.tool for s in self.unrecoverable],
            "ordering_hint": self.ordering_hint,
            "findings": [f.to_json() for f in self.findings],
        }


def compensation_plan(steps: list[Step], *, executed: int | None = None) -> Plan:
    """Work out how to undo what has been done, and whether it can be.

    Called with ``executed`` after a partial failure to produce the actual unwind, and
    without it *before* starting to find out whether an unwind would be possible at
    all. The second use is the valuable one: discovering that step two cannot be undone
    is much cheaper before step one than after step three.

    Compensations run in reverse order, which is not a stylistic choice — a later step
    may depend on an earlier one, so undoing the earlier one first can leave the system
    in a state the later compensator cannot handle.

    The ordering hint applies the one structural rule that actually prevents this class
    of failure: do the reversible work first. A sequence that sends the email and then
    attempts the charge cannot be unwound when the charge fails; the same sequence in
    the other order can.
    """
    executed = len(steps) if executed is None else executed
    done = steps[:executed]

    compensations = [s for s in reversed(done) if s.recoverable]
    unrecoverable = [s for s in reversed(done) if not s.recoverable]

    findings: list[ReplayFinding] = []
    for step in unrecoverable:
        findings.append(
            ReplayFinding(
                "no-compensation",
                f"'{step.tool}' has already run and "
                + (
                    "cannot be undone — the effect has left the system"
                    if step.irreversible
                    else "declares no compensating action"
                ),
                "critical" if step.irreversible else "high",
                {"tool": step.tool, "irreversible": step.irreversible},
            )
        )

    # The ordering rule: any irreversible step that is not last leaves everything after
    # it unable to fail safely.
    ordering_hint: list[str] = []
    last_irreversible = max((i for i, s in enumerate(steps) if not s.recoverable), default=-1)
    if 0 <= last_irreversible < len(steps) - 1:
        exposed = [s.tool for s in steps[last_irreversible + 1 :]]
        findings.append(
            ReplayFinding(
                "irreversible-before-fallible",
                f"'{steps[last_irreversible].tool}' cannot be undone and runs before "
                f"{exposed} — if any of those fail, the sequence cannot be unwound",
                "high",
                {"irreversible": steps[last_irreversible].tool, "exposed": exposed},
            )
        )
        ordering_hint = [s.tool for s in steps if s.recoverable] + [
            s.tool for s in steps if not s.recoverable
        ]

    return Plan(compensations, unrecoverable, findings, ordering_hint)


# --- Cascade (F3.9) --------------------------------------------------------


@dataclass
class Cascade:
    """Everything one call sets off, transitively."""

    root: str
    reached: list[str] = field(default_factory=list)
    depth: int = 0
    cycles: list[list[str]] = field(default_factory=list)
    findings: list[ReplayFinding] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if any(f.severity == "critical" for f in self.findings):
            return "block"
        return "escalate" if self.findings else "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "reached": self.reached,
            "depth": self.depth,
            "cycles": self.cycles,
            "verdict": self.verdict,
            "findings": [f.to_json() for f in self.findings],
        }


def cascade_risk(
    tool: str,
    triggers: dict[str, list[str]],
    *,
    depth_limit: int = 3,
    fan_out_limit: int = 10,
    destructive: tuple[str, ...] = (),
) -> Cascade:
    """Follow what a call sets off, through triggers, webhooks and fan-out.

    Blast-radius analysis is statement-local: it can tell you that one UPDATE touches
    one row, and it has no way to know that a trigger on that table publishes an event
    that four subscribers act on. The second-order effects are where the surprise is,
    and they are only visible in the *declared* wiring — which means this is exactly as
    good as the registry it is given, and no better.

    That limitation is worth stating rather than hiding: an undeclared webhook is
    invisible here. What this catches is the cascade somebody wrote down and nobody
    added up.
    """
    reached: list[str] = []
    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()
    max_depth = 0

    def walk(node: str, path: list[str]) -> None:
        nonlocal max_depth
        for child in triggers.get(node, []):
            if child in path:
                cycle = path[path.index(child) :] + [child]
                core = tuple(cycle[:-1])
                spin = min(range(len(core)), key=lambda i: core[i])
                canonical = core[spin:] + core[:spin]
                if canonical not in seen_cycles:
                    seen_cycles.add(canonical)
                    cycles.append(list(canonical) + [canonical[0]])
                continue
            if child not in reached:
                reached.append(child)
            max_depth = max(max_depth, len(path))
            walk(child, path + [child])

    walk(tool, [tool])

    findings: list[ReplayFinding] = []
    if cycles:
        findings.append(
            ReplayFinding(
                "cascade-cycle",
                f"the declared triggers form a loop: {' -> '.join(cycles[0])}",
                "critical",
                {"cycles": cycles},
            )
        )
    if max_depth > depth_limit:
        findings.append(
            ReplayFinding(
                "cascade-too-deep",
                f"one call to '{tool}' reaches {max_depth} levels of downstream effect",
                "high",
                {"depth": max_depth, "limit": depth_limit},
            )
        )
    if len(reached) > fan_out_limit:
        findings.append(
            ReplayFinding(
                "cascade-fan-out",
                f"one call to '{tool}' sets off {len(reached)} further effects",
                "high",
                {"reached": len(reached), "limit": fan_out_limit},
            )
        )
    hit = [t for t in reached if t in destructive]
    if hit:
        findings.append(
            ReplayFinding(
                "cascade-reaches-destructive",
                f"'{tool}' looks harmless but reaches {hit} through declared triggers",
                "critical",
                {"destructive": hit},
            )
        )

    return Cascade(root=tool, reached=reached, depth=max_depth, cycles=cycles, findings=findings)


# --- Aggregate -------------------------------------------------------------


_TOOL_PATH = re.compile(r"^[\w.-]+$")


@dataclass
class EffectAssessment:
    replay: list[ReplayFinding] = field(default_factory=list)
    plan: Plan | None = None
    cascade: Cascade | None = None

    @property
    def findings(self) -> list[ReplayFinding]:
        out = list(self.replay)
        if self.plan:
            out += self.plan.findings
        if self.cascade:
            out += self.cascade.findings
        return out

    @property
    def verdict(self) -> str:
        severities = {f.severity for f in self.findings}
        if "critical" in severities:
            return "block"
        if severities:
            return "escalate"
        return "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "replay": [f.to_json() for f in self.replay],
            "plan": self.plan.to_json() if self.plan else None,
            "cascade": self.cascade.to_json() if self.cascade else None,
        }


def assess_effects(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    ledger: EffectLedger | None = None,
    key: str | None = None,
    effectful: bool = True,
    steps: list[Step] | None = None,
    triggers: dict[str, list[str]] | None = None,
    destructive: tuple[str, ...] = (),
) -> EffectAssessment:
    """Everything F3 can say about one effectful call, before it is made."""
    return EffectAssessment(
        replay=(ledger.check(tool, arguments, key=key, effectful=effectful) if ledger else []),
        plan=compensation_plan(steps) if steps else None,
        cascade=(cascade_risk(tool, triggers, destructive=destructive) if triggers else None),
    )
