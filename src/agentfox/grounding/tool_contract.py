"""Did the tool answer the question that was asked?

Nothing between the request and the result checks that they match. The agent asks for
order A-1182, the tool returns order A-1183, and every downstream control is satisfied:
the call was authorised, the arguments were untainted, the response is well-formed JSON,
the answer is perfectly grounded in it. Groundedness is measured *against the retrieved
context*, so an answer faithfully describing the wrong record scores 1.0 — and it is
more dangerous than an ungrounded one, because every quality signal says it is fine.

Four things go wrong between asking and receiving, and they fail in different ways:

**Wrong subject.** The result is about a different entity than the request named. This
is the one that ends up in a regulator's letter, because the agent then tells one
customer another customer's balance in complete good faith.

**Silent failure.** A 200 response carrying ``{"error": "timeout"}``, or an empty result
set for a question that presupposes rows. The transport succeeded; the call did not.
Agents read the payload and answer from whatever is in it, including nothing.

**Over-fetch.** The request was for one record and five hundred came back. Whether or
not the extra rows reach the user, the query that produced them was not the query the
request implied, and the surplus is now in the context window where a later turn can
disclose it.

**Missing what was asked for.** The request named three fields; the result carries two.
The agent will answer about the two and say nothing about the third, and the omission
is invisible in the answer.

All of this is checkable without a model, and a model would be the wrong instrument:
asked "does this result answer this request?", it reads a fluent, on-topic record and
says yes. Identifier equality does not have that failure mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- Extraction ------------------------------------------------------------

#: Identifiers a request can name. Deliberately structural: an id is recognised by its
#: shape, not by a list of known formats, because every schema invents its own.
#: The `#` form cannot sit inside a leading \b — `#` is not a word character, so the
#: boundary fails against the space before it and ticket references were silently never
#: matched. Each alternative carries its own anchoring.
_IDENTIFIER = re.compile(
    r"\b[A-Z]{1,5}-\d{2,}\b"  # A-1182, ORD-4471
    r"|(?<![\w#])#\d{3,}\b"  # #44712
    r"|\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"  # an email
    r"|\b\d{6,}\b"  # a long bare number
)

#: Field names a request asks for. "the balance and the due date" -> balance, due date.
_FIELD_WORDS = (
    "balance",
    "total",
    "amount",
    "status",
    "due date",
    "due_date",
    "email",
    "phone",
    "address",
    "name",
    "date",
    "quantity",
    "price",
    "rate",
    "limit",
    "expiry",
    "tracking",
    "reference",
    "reason",
    "owner",
    "tier",
    "plan",
)

#: Payload keys that mean the call failed while the transport succeeded.
_ERROR_KEYS = ("error", "errors", "error_message", "exception", "fault", "failure")

#: Values that mean the same thing.
_ERROR_VALUES = re.compile(
    r"^\s*(?:error|failed|failure|timeout|timed out|unavailable|not found|"
    r"internal server error|502|503|504)\b",
    re.I,
)


def identifiers(text: str) -> set[str]:
    return {m.group(0).lower() for m in _IDENTIFIER.finditer(text or "")}


def _walk(value: Any) -> list[Any]:
    """Every scalar in a nested payload, flattened."""
    if isinstance(value, dict):
        return [x for v in value.values() for x in _walk(v)]
    if isinstance(value, (list, tuple)):
        return [x for v in value for x in _walk(v)]
    return [value]


def _row_count(result: Any) -> int:
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for key in ("rows", "results", "items", "data", "records"):
            value = result.get(key)
            if isinstance(value, list):
                return len(value)
        return 1 if result else 0
    return 1 if result not in (None, "") else 0


def requested_fields(request: str) -> set[str]:
    """Field names the request asks for, longest match winning.

    "due date" contains "date", so a naive substring pass reports both and then flags
    the result for missing a field nobody asked for. Shorter matches contained in a
    longer one are dropped.
    """
    lowered = " ".join((request or "").lower().split())
    hits = {f.replace("_", " ") for f in _FIELD_WORDS if f.replace("_", " ") in lowered}
    return {f for f in hits if not any(f != other and f in other for other in hits)}


def _present_keys(result: Any) -> set[str]:
    keys: set[str] = set()
    stack = [result]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            keys |= {str(k).lower().replace("_", " ") for k in node}
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    return keys


# --- Findings --------------------------------------------------------------


@dataclass
class ContractFinding:
    code: str
    detail: str
    severity: str = "high"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "severity": self.severity,
            "evidence": self.evidence,
        }


@dataclass
class ContractCheck:
    findings: list[ContractFinding] = field(default_factory=list)
    asked_for: list[str] = field(default_factory=list)
    returned: list[str] = field(default_factory=list)
    rows: int = 0

    @property
    def satisfied(self) -> bool:
        return not self.findings

    @property
    def verdict(self) -> str:
        severities = {f.severity for f in self.findings}
        if "critical" in severities:
            return "block"
        return "escalate" if severities else "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "verdict": self.verdict,
            "asked_for": self.asked_for,
            "returned": self.returned,
            "rows": self.rows,
            "findings": [f.to_json() for f in self.findings],
        }


def answers_request(
    request: str,
    result: Any,
    *,
    expect_rows: int | None = None,
    expect_fields: list[str] | None = None,
    presupposes_rows: bool = True,
) -> ContractCheck:
    """Check a tool result against the request that produced it.

    ``expect_rows`` is the count the request implies — one, for a lookup by id. Left
    unset, a lookup naming a single identifier implies one, which is inferred rather
    than demanded.

    ``presupposes_rows`` distinguishes "what is this customer's balance" from "does this
    customer have any open tickets". An empty result is a silent failure for the first
    and a valid answer for the second, and nothing in the payload tells them apart —
    only the caller knows, so the caller says.
    """
    check = ContractCheck(rows=_row_count(result))

    asked = identifiers(request)
    returned = identifiers(" ".join(str(v) for v in _walk(result)))
    check.asked_for = sorted(asked)
    check.returned = sorted(returned)

    # --- wrong subject
    if asked and returned and not (asked & returned):
        check.findings.append(
            ContractFinding(
                "subject-mismatch",
                f"the request named {sorted(asked)} and the result carries "
                f"{sorted(returned)} — nothing in common. Every downstream control will "
                "pass: the answer will be perfectly grounded in the wrong record",
                "critical",
                {"asked": sorted(asked), "returned": sorted(returned)},
            )
        )
    elif asked and not returned and check.rows:
        check.findings.append(
            ContractFinding(
                "subject-unverifiable",
                f"the request named {sorted(asked)} and the result carries no identifier, "
                "so there is no way to confirm it is about the right record",
                "medium",
                {"asked": sorted(asked)},
            )
        )

    # --- silent failure
    error = _errors_in(result)
    if error:
        check.findings.append(
            ContractFinding(
                "error-in-successful-response",
                f"the call reported success and the payload carries an error: {error}. "
                "An agent reads the payload, not the status",
                "critical",
                {"error": error},
            )
        )
    elif check.rows == 0 and presupposes_rows:
        check.findings.append(
            ContractFinding(
                "empty-result-for-a-question-that-presupposes-rows",
                "the tool returned nothing for a request that assumes a record exists; "
                "answering from an empty result is how a confident wrong answer is built",
                "high",
                {},
            )
        )

    # --- over-fetch
    implied = expect_rows if expect_rows is not None else (1 if len(asked) == 1 else None)
    if implied is not None and check.rows > implied:
        check.findings.append(
            ContractFinding(
                "over-fetch",
                f"the request implied {implied} record(s) and {check.rows} came back. "
                "Whether or not the surplus reaches the user, it is now in the context "
                "window where a later turn can disclose it",
                "high" if check.rows > implied * 10 else "medium",
                {"implied": implied, "returned": check.rows},
            )
        )

    # --- missing what was asked for
    #
    # Only meaningful once the call actually returned something. Reporting absent
    # fields on top of an error or an empty result is a second finding about the same
    # event, and a check that reports twice is a check people learn to skim.
    wanted = {f.lower().replace("_", " ") for f in (expect_fields or [])} or requested_fields(
        request
    )
    if wanted and not error and check.rows:
        present = _present_keys(result)
        if missing := sorted(wanted - present):
            check.findings.append(
                ContractFinding(
                    "missing-requested-field",
                    f"the request asked for {missing} and the result does not carry "
                    "them. The agent will answer about the rest and the omission will not "
                    "appear anywhere in the answer",
                    "medium",
                    {"missing": missing},
                )
            )

    return check


def _errors_in(result: Any) -> str | None:
    if isinstance(result, dict):
        for key in _ERROR_KEYS:
            value = result.get(key)
            if value:
                return str(value)[:120]
    for scalar in _walk(result):
        if isinstance(scalar, str) and _ERROR_VALUES.match(scalar):
            return scalar[:120]
    return None
