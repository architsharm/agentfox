"""Threshold ladders — the shape almost every business guardrail actually takes.

*"Refunds under $10 auto-approve; $10–100 run a validation check; over $100 needs a
human."*

That sentence is the single most common form of governance a business hands an
engineering team, and the existing policy engine cannot express it. Written as three
ordinary rules it produces two silent defects, both reproduced before this module was
written:

* ``lt 10`` and ``gt 10`` leave **exactly 10 uncovered** — the request falls through to
  the default with no rule fired and nothing to see in the trace.
* At 500 both the middle and top rules fire, because the engine evaluates every rule
  and takes the strongest. Bands are not mutually exclusive, so a band can never be
  *weaker* than one below it — "over 100 auto-approves for trusted merchants" is
  inexpressible.

And no effect in the lattice means *"run a check and decide from its result"*. Every
existing effect is restrictive: allow, redact, abstain, escalate, block. A validation
step is procedural, and procedural outcomes are most of what a business asks for.

**The two algebras.** This is the part that makes the architecture tricky, and the
reason ladders are a separate construct rather than more rules:

* Security guardrails compose by **lattice maximum**. Every rule is evaluated, the
  strongest effect wins, and adding a rule can only ever tighten. That is correct: a
  new detector must not be able to weaken an existing block.
* Business guardrails compose by **exactly-one-band**. A ladder selects a single
  outcome, and adding a band changes *which* one applies rather than strengthening the
  result.

Mixing them in one flat list gives you the worst of both. So ladders evaluate
separately and then combine with security-dominates: a ladder may never soften a
security verdict, and an auto-approve band cannot override a block. It can only ever
make a business decision *within* what security already permits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

#: What a band can decide. `verify` is the new one and the reason this module exists.
OUTCOMES = ("allow", "verify", "escalate", "block", "redact")

#: Currency and unit handling is explicit because a bare threshold is a bug waiting to
#: happen: one team means dollars, another means cents, and the ladder silently
#: approves a hundred-fold larger refund.
KNOWN_UNITS = ("USD", "EUR", "GBP", "JPY", "USD_CENTS", "EUR_CENTS", "GBP_CENTS", "count", "days")

_MONEY = re.compile(r"^\s*([£$€¥])?\s*(-?[\d,]+(?:\.\d+)?)\s*([A-Za-z]{3})?\s*$")
_SYMBOL_TO_CODE = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY"}


class VerifySpec(BaseModel):
    """A check to run before deciding, and what to do when it does not pass."""

    check: str = Field(description="Tool or check key to invoke, e.g. 'risk.refund_check'.")
    arguments: dict[str, Any] = Field(default_factory=dict)
    #: What "passed" looks like in the check's result. Absent means truthiness.
    expect: dict[str, Any] = Field(default_factory=dict)
    on_pass: str = "allow"
    on_fail: str = "escalate"
    #: A check that could not run is not a check that passed. Fail closed by default.
    on_error: str = "escalate"
    timeout_ms: int = 5_000

    @field_validator("on_pass", "on_fail", "on_error")
    @classmethod
    def _known_outcome(cls, value: str) -> str:
        if value not in ("allow", "escalate", "block", "redact"):
            raise ValueError(f"'{value}' is not a terminal outcome")
        return value


class Band(BaseModel):
    """One rung. ``upto`` is inclusive; the final band omits it and is open-ended."""

    upto: float | None = None
    outcome: str = "allow"
    reason: str = ""
    verify: VerifySpec | None = None
    approver_role: str | None = None
    label: str = ""

    @field_validator("outcome")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}, got '{value}'")
        return value

    @model_validator(mode="after")
    def _verify_is_configured(self) -> Band:
        if self.outcome == "verify" and self.verify is None:
            raise ValueError("a 'verify' band must declare what to check")
        return self


class Ladder(BaseModel):
    """An ordered set of mutually exclusive bands over one numeric field.

    Bands are half-open by construction — band *n* covers ``(previous.upto,
    this.upto]`` — so gaps and overlaps are impossible to author. That is the whole
    point: the defect this replaces was a boundary that belonged to no rule.
    """

    key: str
    name: str = ""
    description: str = ""
    #: Which requests this ladder governs. Same shape as a policy rule's `when`.
    tool: str | None = None
    surface: str = "tool_args"
    agent: str | None = None
    #: Dotted path into the request, e.g. "arguments.amount".
    field_path: str = Field(alias="field")
    unit: str = "count"
    bands: list[Band]
    #: Who agreed this, so a disagreement has someone to resolve it.
    owner: str = ""
    mode: str = "observe"

    model_config = {"populate_by_name": True}

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, value: str) -> str:
        if value not in KNOWN_UNITS:
            raise ValueError(f"unit must be one of {KNOWN_UNITS}, got '{value}'")
        return value

    @model_validator(mode="after")
    def _bands_are_ordered_and_closed(self) -> Ladder:
        if not self.bands:
            raise ValueError("a ladder needs at least one band")
        previous: float | None = None
        for index, band in enumerate(self.bands[:-1]):
            if band.upto is None:
                raise ValueError(
                    f"band {index} has no 'upto' but is not last — only the final band "
                    "may be open-ended, or the bands below it are unreachable"
                )
            if previous is not None and band.upto <= previous:
                raise ValueError(
                    f"band {index} ends at {band.upto}, at or below the previous band's "
                    f"{previous} — bands must ascend or the lower one never matches"
                )
            previous = band.upto
        if self.bands[-1].upto is not None:
            raise ValueError(
                "the final band must omit 'upto' so the ladder is total — otherwise a "
                "value above the last threshold matches nothing, which is the silent "
                "hole this construct exists to remove"
            )
        return self

    def intervals(self) -> list[tuple[float | None, float | None, Band]]:
        """Resolved half-open intervals, for showing an author what they wrote."""
        out: list[tuple[float | None, float | None, Band]] = []
        lower: float | None = None
        for band in self.bands:
            out.append((lower, band.upto, band))
            lower = band.upto
        return out


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass
class LadderDecision:
    """What the ladder decided, and enough context to explain it to a human."""

    ladder_key: str
    matched: bool = False
    band_index: int | None = None
    outcome: str = "allow"
    value: float | None = None
    unit: str = ""
    reason: str = ""
    verify: VerifySpec | None = None
    approver_role: str | None = None
    #: Set when the ladder could not decide — a missing field, a bad unit. Never
    #: silently allows: an undecidable ladder escalates.
    undecidable: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "ladder": self.ladder_key,
            "matched": self.matched,
            "band": self.band_index,
            "outcome": self.outcome,
            "value": self.value,
            "unit": self.unit,
            "reason": self.reason,
            "approver_role": self.approver_role,
            "undecidable": self.undecidable,
            "verify": self.verify.model_dump() if self.verify else None,
        }


def parse_amount(raw: Any, expected_unit: str) -> tuple[float | None, str]:
    """Read a numeric value, refusing to guess across currencies.

    ``"$150"`` against a ladder in EUR is not 150 — it is a question nobody has
    answered, and converting it silently is how a threshold agreed in one currency
    starts approving in another.
    """
    if isinstance(raw, bool):
        return None, "a boolean is not an amount"
    if isinstance(raw, (int, float)):
        return float(raw), ""
    if not isinstance(raw, str):
        return None, f"cannot read {type(raw).__name__} as an amount"

    match = _MONEY.match(raw)
    if not match:
        return None, f"'{raw[:24]}' is not a number"
    symbol, digits, code = match.groups()
    found = code.upper() if code else (_SYMBOL_TO_CODE.get(symbol or "") or "")
    if found:
        base = expected_unit.replace("_CENTS", "")
        if found != base:
            return None, (
                f"value is in {found} but the ladder is in {expected_unit}; refusing to "
                "convert — a threshold agreed in one currency must not silently apply "
                "in another"
            )
    try:
        return float(digits.replace(",", "")), ""
    except ValueError:
        return None, f"'{digits}' is not a number"


def _read_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def evaluate(ladder: Ladder, request: dict[str, Any]) -> LadderDecision:
    """Select exactly one band, or say why it could not.

    An undecidable ladder escalates rather than allowing. A threshold you could not
    evaluate is not a threshold that was satisfied, and defaulting to allow would make
    a missing field the cheapest way past a control.
    """
    decision = LadderDecision(ladder_key=ladder.key, unit=ladder.unit)
    raw = _read_path(request, ladder.field_path)
    if raw is None:
        decision.undecidable = f"'{ladder.field_path}' is not present in the request"
        decision.outcome = "escalate"
        decision.reason = decision.undecidable
        return decision

    value, problem = parse_amount(raw, ladder.unit)
    if value is None:
        decision.undecidable = problem
        decision.outcome = "escalate"
        decision.reason = problem
        return decision

    decision.value = value
    if value < 0:
        # A negative refund is a charge. Whatever the bands say, it is not the thing
        # they were written about.
        decision.undecidable = f"negative value {value:g} — the bands were written for positives"
        decision.outcome = "escalate"
        decision.reason = decision.undecidable
        return decision

    for index, (_lower, upper, band) in enumerate(ladder.intervals()):
        if upper is None or value <= upper:
            decision.matched = True
            decision.band_index = index
            decision.outcome = band.outcome
            decision.verify = band.verify
            decision.approver_role = band.approver_role
            decision.reason = band.reason or _describe(ladder, index, value)
            return decision

    # Unreachable: the model validator guarantees an open-ended final band.
    decision.undecidable = "no band matched despite a total ladder"
    decision.outcome = "escalate"
    return decision


def _describe(ladder: Ladder, index: int, value: float) -> str:
    lower, upper, band = ladder.intervals()[index]
    if lower is None and upper is not None:
        window = f"at or below {upper:g}"
    elif upper is None:
        window = f"above {lower:g}"
    else:
        window = f"between {lower:g} (exclusive) and {upper:g}"
    return f"{ladder.field_path} = {value:g} {ladder.unit}, {window} → {band.outcome}"


# ---------------------------------------------------------------------------
# Running the verification step
# ---------------------------------------------------------------------------


@dataclass
class VerifyResult:
    """What the check said, and what that means for the request."""

    ran: bool
    passed: bool
    outcome: str
    detail: str = ""
    raw: Any = None

    def to_json(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "passed": self.passed,
            "outcome": self.outcome,
            "detail": self.detail,
        }


def _satisfies(result: Any, expect: dict[str, Any]) -> tuple[bool, str]:
    """Does the check's result meet the expectation?

    An empty expectation means truthiness, which is the common case and the one people
    write first. Anything more specific is expressed the same way argument constraints
    are, so an author who has written one has written both.
    """
    if not expect:
        return bool(result), "truthy" if result else "falsy"
    if not isinstance(result, dict):
        return False, f"expected an object to match against, got {type(result).__name__}"

    from agentfox.policy.model import COMPARATORS

    for path, condition in expect.items():
        value: Any = result
        for part in str(path).split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(condition, dict) and "op" in condition:
            comparator = COMPARATORS.get(condition["op"])
            if comparator is None:
                return False, f"unknown operator '{condition['op']}'"
            if not comparator(value, condition.get("value")):
                return False, f"{path}={value!r} fails {condition['op']} {condition.get('value')!r}"
        elif value != condition:
            return False, f"{path}={value!r} is not {condition!r}"
    return True, "all expectations met"


def run_verification(spec: VerifySpec, runner: Any) -> VerifyResult:
    """Execute a verification step through a caller-supplied runner.

    ``runner`` is any callable ``(check, arguments) -> result``. AgentFox does not own
    the tool runtime — the same reasoning as the MCP governor — so the caller injects
    it, and that keeps this usable with an MCP server, a LangGraph node, or a plain
    function without importing any of them.

    A check that raises is *not* a check that passed. That is the whole point of the
    construct: the failure mode being designed against is a validation step that
    quietly stops validating.
    """
    if runner is None:
        return VerifyResult(
            ran=False,
            passed=False,
            outcome=spec.on_error,
            detail="no verification runner supplied — a check that cannot run has not passed",
        )
    try:
        raw = runner(spec.check, dict(spec.arguments))
    except Exception as exc:
        return VerifyResult(
            ran=False,
            passed=False,
            outcome=spec.on_error,
            detail=f"{spec.check} raised {type(exc).__name__}: {exc}",
        )
    passed, why = _satisfies(raw, spec.expect)
    return VerifyResult(
        ran=True,
        passed=passed,
        outcome=spec.on_pass if passed else spec.on_fail,
        detail=f"{spec.check}: {why}",
        raw=raw,
    )
