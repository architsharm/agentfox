"""P13 — failure attribution and handoff fidelity.

*"Step 3 was subtly wrong. By step 8 no single step looks wrong."*

Two questions this answers, and they are the same question at different scales.

**Which step actually broke it.** A trace records what happened, so after a failure
everyone can see the path — and the path is misleading. The step that failed is almost
never the step that was wrong; it is the step where a value that had been travelling
quietly since much earlier finally hit something that checked it. Blaming the last
actor to touch a value is the default reading of a trace and it is wrong in exactly the
cases that matter, because the steps in between look fine: they received a number and
passed it on, which is what they were supposed to do.

So attribution here is a data-flow question, not a chronology question. Walk backwards
from the value that failed and find the first step that *originated* it — produced it
without having received it. Everything after that propagated someone else's mistake.

**What was lost at the handoff.** A subagent receives a summary, and a summary is
lossy by construction. "Urgent, refund under £500, do not contact the customer" becomes
"process this refund", which is a faithful summary of the request and drops every
constraint on it. The subagent then does exactly what it was told. Nothing in the trace
looks like an error — there is no exception, no refusal, no contradiction — and the
constraint the parent was given by a human is simply not in the system any more.

Both are deterministic. Extracting an amount, a deadline, a prohibition or an
identifier from an instruction is parsing; checking whether it survived into the next
instruction is set difference. A model is not needed and would be worse: asked whether
a summary preserves a constraint, it tends to say yes, because the summary reads well.

The limit is worth stating plainly. This finds constraints that were *written down* and
then dropped. A constraint that was never in the parent instruction — an expectation
the human held and never typed — is invisible here, and no amount of trace analysis
recovers it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- Constraints -----------------------------------------------------------

#: A monetary or numeric limit with the direction it constrains.
_LIMIT = re.compile(
    r"\b(under|below|less than|no more than|at most|up to|over|above|more than|"
    r"at least|exceeding|maximum of|minimum of|within)\s+"
    r"([£$€¥]?\s?\d[\d,]*(?:\.\d+)?)\s*"
    r"(k\b|m\b|thousand|million|dollars?|euros?|pounds?|days?|hours?|minutes?|"
    r"items?|records?|times?)?",
    re.I,
)

#: An explicit prohibition. These are the constraints most often dropped by a summary,
#: because a summary describes what to do and a prohibition describes what not to.
_PROHIBITION = re.compile(
    r"\b(?:do not|don't|never|must not|cannot|shall not|without|avoid|refrain from|"
    r"under no circumstances)\s+([a-z][\w' -]{2,40})",
    re.I,
)

#: Urgency and deadlines. Dropped silently because the child still completes the task,
#: just not in time.
_URGENCY = re.compile(
    r"\b(urgent|urgently|immediately|asap|same day|today|by (?:end of )?(?:day|week|"
    r"tomorrow|monday|tuesday|wednesday|thursday|friday)|priority|expedite[d]?|"
    r"time[- ]sensitive)\b",
    re.I,
)

#: Identifiers: order numbers, ticket ids, emails, account references. A handoff that
#: loses the identifier sends the child to act on the wrong record.
_IDENTIFIER = re.compile(
    r"\b(?:[A-Z]{2,}-\d{2,}|#\d{3,}|\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b|\b\d{6,}\b)"
)

#: A required approval or review. Dropping this converts a gated action into an
#: ungated one, which is the failure with the largest blast radius in this module.
_APPROVAL = re.compile(
    r"\b(?:require[sd]?|need[s]?|must (?:get|obtain|have)|subject to|only with|"
    r"pending)\s+(?:\w+\s+){0,3}?(approval|authorisation|authorization|sign-?off|"
    r"review|confirmation)\b",
    re.I,
)

#: A directive-shaped clause not covered by any of the five typed categories above
#: — "make sure the vendor doesn't find out about the discount" carries a real
#: constraint (confidentiality) that matches none of LIMIT/PROHIBITION/URGENCY/
#: IDENTIFIER/APPROVAL. Narrow on purpose: this is a *signal*, not a general
#: imperative-mood detector — that would need real NLP, and this module's whole
#: design is deterministic regex over open-ended parsing. It catches the common
#: phrasings a human uses to flag "this matters" without claiming to catch every
#: way an instruction can carry a requirement no typed category models.
_UNCLASSIFIED_DIRECTIVE = re.compile(
    r"\b(?:make sure|be sure to|ensure that|ensure|keep (?:this |it )?(?:confidential|"
    r"private|secret|quiet)|don'?t (?:mention|tell|disclose|reveal|let)|do not "
    r"(?:mention|tell|disclose|reveal|let)|remember to|don'?t forget to|note that|"
    r"make it clear that|keep in mind)\b[^.;]{0,80}",
    re.I,
)

LIMIT = "limit"
PROHIBITION = "prohibition"
URGENCY = "urgency"
IDENTIFIER = "identifier"
APPROVAL = "approval"
#: A structured constraint pulled from a granted Capability's own constraints_json
#: (models.py's Capability, P2-2), not from instruction prose — see
#: handoff_fidelity's capability_constraints parameter.
CAPABILITY = "capability"

#: How much dropping each kind costs. An approval gate and a prohibition change what
#: the child is *permitted* to do; urgency changes only when it does it.
_WEIGHT = {APPROVAL: 3.0, PROHIBITION: 3.0, LIMIT: 2.5, IDENTIFIER: 2.0, URGENCY: 1.0}


@dataclass(frozen=True)
class Constraint:
    """One thing an instruction requires, in a form that survives comparison."""

    kind: str
    value: str
    source: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value, "source": self.source}


def _norm(text: str) -> str:
    return " ".join(text.lower().split()).strip(" .,;:")


def extract_constraints(text: str) -> list[Constraint]:
    """Pull the checkable requirements out of an instruction.

    Normalised on the way out so that "under £500" and "under 500 pounds" compare
    equal — a handoff that rephrases a constraint has not dropped it, and reporting
    that it has would bury the real losses in noise.
    """
    if not text:
        return []
    flat = " ".join(text.split())
    found: list[Constraint] = []

    for match in _LIMIT.finditer(flat):
        direction = _norm(match.group(1))
        amount = re.sub(r"[\s,]", "", match.group(2))
        unit = _norm(match.group(3) or "")
        unit = {
            "dollars": "usd",
            "dollar": "usd",
            "euros": "eur",
            "euro": "eur",
            "pounds": "gbp",
            "pound": "gbp",
        }.get(unit, unit)
        if amount.startswith(("£", "$", "€", "¥")):
            unit = {"£": "gbp", "$": "usd", "€": "eur", "¥": "jpy"}[amount[0]]
            amount = amount[1:]
        direction = (
            "under"
            if direction
            in (
                "under",
                "below",
                "less than",
                "no more than",
                "at most",
                "up to",
                "maximum of",
                "within",
            )
            else "over"
        )
        found.append(
            Constraint(LIMIT, f"{direction} {amount}{' ' + unit if unit else ''}", match.group(0))
        )

    for match in _APPROVAL.finditer(flat):
        found.append(Constraint(APPROVAL, "approval", match.group(0)))

    for match in _PROHIBITION.finditer(flat):
        found.append(Constraint(PROHIBITION, _norm(match.group(1)), match.group(0)))

    for match in _URGENCY.finditer(flat):
        found.append(Constraint(URGENCY, "urgent", match.group(0)))

    for match in _IDENTIFIER.finditer(flat):
        found.append(Constraint(IDENTIFIER, _norm(match.group(0)), match.group(0)))

    # Deduplicate on (kind, value): an instruction that says "urgent" twice carries one
    # constraint, and counting it twice would distort the fidelity score.
    seen: set[tuple[str, str]] = set()
    unique = []
    for constraint in found:
        key = (constraint.kind, constraint.value)
        if key not in seen:
            seen.add(key)
            unique.append(constraint)
    return unique


def _unclassified_directives(text: str) -> list[str]:
    """Directive-shaped clauses not covered by any of the five typed constraint
    kinds — flagged as text, not compared by (kind, value) equality the way a
    limit or an identifier is, since these are not normalised into a form that
    comparison makes sense for. Mirrors `attribute()`'s own honesty pattern
    (returning `confident=False` rather than staying silent when it cannot
    originate a value) for the handoff side: a written constraint outside the
    five regex kinds is surfaced, not silently dropped from the picture.
    """
    if not text:
        return []
    flat = " ".join(text.split())
    typed_spans = [
        (m.start(), m.end())
        for pattern in (_LIMIT, _APPROVAL, _PROHIBITION, _URGENCY, _IDENTIFIER)
        for m in pattern.finditer(flat)
    ]
    found: list[str] = []
    for match in _UNCLASSIFIED_DIRECTIVE.finditer(flat):
        # Skip a match already claimed by a typed extractor — "you must not
        # mention the discount" is a prohibition, not also an unclassified one.
        if any(match.start() < end and start < match.end() for start, end in typed_spans):
            continue
        found.append(_norm(match.group(0)))
    return found


def _format_capability_constraint(key: str, spec: Any) -> str:
    if isinstance(spec, dict):
        return f"{key} " + ", ".join(f"{op} {val}" for op, val in spec.items())
    return f"{key} = {spec}"


# --- Handoff fidelity (L6.1, L6.2) -----------------------------------------


@dataclass
class Handoff:
    """What survived the trip from one agent's instruction to the next."""

    kept: list[Constraint] = field(default_factory=list)
    dropped: list[Constraint] = field(default_factory=list)
    added: list[Constraint] = field(default_factory=list)
    #: Directive-shaped clauses in the parent that neither reached the child's
    #: text nor match any typed category — see `_unclassified_directives`.
    unclassified: list[str] = field(default_factory=list)
    from_agent: str = ""
    to_agent: str = ""

    @property
    def fidelity(self) -> float:
        """Weighted share of the parent's constraints that reached the child.

        Weighted rather than counted, because dropping an approval gate and dropping a
        deadline are not the same event and a plain ratio says they are.
        """
        total = sum(_WEIGHT.get(c.kind, 1.0) for c in self.kept + self.dropped)
        if not total:
            return 1.0
        return round(sum(_WEIGHT.get(c.kind, 1.0) for c in self.kept) / total, 4)

    @property
    def verdict(self) -> str:
        if any(c.kind in (APPROVAL, PROHIBITION, LIMIT) for c in self.dropped):
            return "block"
        if self.dropped or self.added or self.unclassified:
            return "escalate"
        return "allow"

    def explain(self) -> str:
        if not self.dropped and not self.added and not self.unclassified:
            return "every constraint in the parent instruction reached the child"
        parts = []
        if self.dropped:
            parts.append("dropped " + ", ".join(f"{c.kind}: {c.value}" for c in self.dropped))
        if self.added:
            parts.append("invented " + ", ".join(f"{c.kind}: {c.value}" for c in self.added))
        if self.unclassified:
            parts.append(
                "an instruction-shaped clause did not clearly carry over: "
                + "; ".join(self.unclassified)
            )
        return "; ".join(parts)

    def to_json(self) -> dict[str, Any]:
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "fidelity": self.fidelity,
            "verdict": self.verdict,
            "kept": [c.to_json() for c in self.kept],
            "dropped": [c.to_json() for c in self.dropped],
            "added": [c.to_json() for c in self.added],
            "unclassified": self.unclassified,
            "explanation": self.explain(),
        }


def handoff_fidelity(
    parent: str,
    child: str,
    *,
    from_agent: str = "",
    to_agent: str = "",
    capability_constraints: dict[str, Any] | None = None,
) -> Handoff:
    """Compare the instruction an agent was given against the one it passed on.

    A summary is lossy by construction, and the loss is invisible in a trace: there is
    no exception, no refusal, no contradiction. The child does exactly what it was told
    and the constraint a human placed on the work is no longer in the system.

    Constraints *added* by the handoff are reported too. An instruction that acquires a
    limit nobody set is a different failure with the same cause — the intermediate step
    is writing requirements rather than relaying them.

    ``capability_constraints`` widens what counts as a declared constraint beyond
    instruction prose: the child's own granted `Capability.constraints_json`
    (P2-2), when a caller has it in hand. A limit enforced there is real —
    checked on every call, independent of what either agent's instruction says —
    so it is folded into ``kept`` even when neither instruction mentions it,
    rather than leaving a caller to conclude a dropped mention means the
    constraint no longer exists anywhere in the system.
    """
    parent_constraints = extract_constraints(parent)
    child_constraints = extract_constraints(child)
    child_keys = {(c.kind, c.value) for c in child_constraints}
    parent_keys = {(c.kind, c.value) for c in parent_constraints}

    parent_unclassified = _unclassified_directives(parent)
    child_norm = _norm(child)
    unclassified = [d for d in parent_unclassified if d not in child_norm]

    enforced = [
        Constraint(CAPABILITY, _format_capability_constraint(key, spec))
        for key, spec in (capability_constraints or {}).items()
    ]

    return Handoff(
        kept=[c for c in parent_constraints if (c.kind, c.value) in child_keys] + enforced,
        dropped=[c for c in parent_constraints if (c.kind, c.value) not in child_keys],
        added=[c for c in child_constraints if (c.kind, c.value) not in parent_keys],
        unclassified=unclassified,
        from_agent=from_agent,
        to_agent=to_agent,
    )


def trace_handoffs(steps: list[dict[str, Any]]) -> list[Handoff]:
    """Fidelity across a chain of delegations.

    Chained because loss compounds: three handoffs that each keep 80% of the
    constraints keep half of them between them, and no single hop looks bad.
    """
    handoffs: list[Handoff] = []
    for parent, child in zip(steps, steps[1:], strict=False):
        handoffs.append(
            handoff_fidelity(
                str(parent.get("instruction", "")),
                str(child.get("instruction", "")),
                from_agent=str(parent.get("agent", "")),
                to_agent=str(child.get("agent", "")),
            )
        )
    return handoffs


# --- Goal drift (L3.2) -----------------------------------------------------


@dataclass
class Drift:
    """How far a run has moved from what it was asked to do."""

    retained: float
    lost: list[Constraint] = field(default_factory=list)
    steps: int = 0

    @property
    def drifted(self) -> bool:
        return self.retained < 0.5

    def to_json(self) -> dict[str, Any]:
        return {
            "retained": self.retained,
            "drifted": self.drifted,
            "steps": self.steps,
            "lost": [c.to_json() for c in self.lost],
        }


def goal_drift(intent: str, trajectory: list[str]) -> Drift:
    """Compare the original request against everything the run has done since.

    Long runs end up solving a different problem, and the step where that happened is
    never marked. Each individual step is a reasonable next action given the previous
    one; it is only against the *original* intent that the divergence is visible, which
    is why this compares to the intent rather than to the previous step.
    """
    wanted = extract_constraints(intent)
    if not wanted:
        return Drift(1.0, [], len(trajectory))
    seen = " ".join(trajectory)
    seen_keys = {(c.kind, c.value) for c in extract_constraints(seen)}
    lost = [c for c in wanted if (c.kind, c.value) not in seen_keys]
    total = sum(_WEIGHT.get(c.kind, 1.0) for c in wanted)
    kept = total - sum(_WEIGHT.get(c.kind, 1.0) for c in lost)
    return Drift(round(kept / total, 4), lost, len(trajectory))


# --- Failure attribution (L3.4, L6.3) --------------------------------------


@dataclass
class Attribution:
    """Which step originated the value that failed, and which merely carried it."""

    origin_step: str | None
    origin_actor: str | None
    propagators: list[str] = field(default_factory=list)
    failed_step: str = ""
    value: str = ""
    confident: bool = True

    def explain(self) -> str:
        if self.origin_step is None:
            return (
                f"'{self.value}' was not produced by any step in the trace — it entered "
                "from outside it, so the origin is not attributable from this trace alone"
            )
        carried = (
            f" {len(self.propagators)} step(s) carried it without changing it"
            if self.propagators
            else ""
        )
        return (
            f"step {self.origin_step} ({self.origin_actor}) originated '{self.value}'; "
            f"step {self.failed_step} is where it was first checked.{carried}"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "origin_step": self.origin_step,
            "origin_actor": self.origin_actor,
            "propagators": self.propagators,
            "failed_step": self.failed_step,
            "value": self.value,
            "confident": self.confident,
            "explanation": self.explain(),
        }


def _carries(step: dict[str, Any], value: str) -> bool:
    return value in str(step.get("output", ""))


def _received(step: dict[str, Any], value: str) -> bool:
    return any(value in str(v) for v in (step.get("inputs") or {}).values())


def attribute(trace: list[dict[str, Any]], *, value: str, failed_step: str = "") -> Attribution:
    """Find the step that introduced a value, not the step that tripped over it.

    The default reading of a trace blames the last actor to touch the value, and that
    reading is wrong in exactly the cases that need attributing: the steps in between
    received a number and passed it on, which is what they were supposed to do.

    A step originates a value when it emits the value without having received it. If no
    step does — the value was present from the first input — that is reported rather
    than pinned on step one, because the origin is genuinely outside this trace.
    """
    failed_step = failed_step or (str(trace[-1].get("id", "")) if trace else "")
    origin = None
    propagators: list[str] = []

    for step in trace:
        step_id = str(step.get("id", ""))
        if not _carries(step, value):
            continue
        if _received(step, value):
            if origin is not None:
                propagators.append(step_id)
            continue
        if origin is None:
            origin = step
        else:
            # A second independent origin: two steps produced the same value from
            # different inputs, so the chain is not a single line.
            propagators.append(step_id)

    if origin is None:
        return Attribution(None, None, [], failed_step, value, confident=False)

    return Attribution(
        origin_step=str(origin.get("id", "")),
        origin_actor=str(origin.get("actor") or origin.get("agent") or ""),
        propagators=[p for p in propagators if p != failed_step],
        failed_step=failed_step,
        value=value,
    )


# --- Delegation graph (L6.6) -----------------------------------------------


@dataclass
class Delegation:
    """Structural problems in who is calling whom."""

    cycles: list[list[str]] = field(default_factory=list)
    max_depth: int = 0
    over_depth: bool = False

    @property
    def verdict(self) -> str:
        return "block" if self.cycles or self.over_depth else "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "cycles": self.cycles,
            "max_depth": self.max_depth,
            "over_depth": self.over_depth,
            "verdict": self.verdict,
        }


def delegation_graph(edges: list[tuple[str, str]], *, depth_limit: int = 5) -> Delegation:
    """Detect agent-to-agent cycles and runaway delegation depth.

    Tool-call loop detection does not see this. A calls B calls A is not a repeated
    tool call — every individual call is to a different agent with different arguments,
    and the loop is only visible in the shape of the graph.
    """
    adjacency: dict[str, list[str]] = {}
    for caller, callee in edges:
        adjacency.setdefault(caller, []).append(callee)
        adjacency.setdefault(callee, [])

    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()
    max_depth = 0

    def walk(node: str, path: list[str], on_path: set[str]) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, len(path))
        for neighbour in adjacency.get(node, []):
            if neighbour in on_path:
                cycle = path[path.index(neighbour) :] + [neighbour]
                # Rotate to a canonical start so A->B->A and B->A->B report once.
                core = cycle[:-1]
                spin = min(range(len(core)), key=lambda i: core[i])
                canonical = tuple(core[spin:] + core[:spin])
                if canonical not in seen_cycles:
                    seen_cycles.add(canonical)
                    cycles.append(list(canonical) + [canonical[0]])
                continue
            walk(neighbour, path + [neighbour], on_path | {neighbour})

    for node in adjacency:
        walk(node, [node], {node})

    return Delegation(cycles=cycles, max_depth=max_depth, over_depth=max_depth > depth_limit)
