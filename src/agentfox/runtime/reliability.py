"""Cost, reliability and degradation (P15).

**Evidence.** Five of eleven senior engineers surveyed built this by hand. Aditya
(Deloitte UK): *"circuit breaker for LLM provider outages, Redis-backpressure request
queuing, provider fallback, and TPM/RPM-aware rate limiting with hard daily caps on
token spend."* Derrick (Murphy USA): *"graceful degradation to smaller LLMs,
sustaining 2x traffic spikes."*

**Why it lives here rather than in a separate gateway.** It sits at exactly the same
interception point as enforcement — same request path, same decision moment, same
audit trail. Building it separately would duplicate the plumbing and, worse, split
the story: "your agent was stopped" and "your agent ran out of budget" are the same
conversation for the person on call.

The piece nobody else ties together: **a budget breach produces an audit entry and a
finding, not just an HTTP 429.** Gateways do routing and cost; none of them make
spend a governed event.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Budget, Finding, utcnow
from agentfox.prove.findings import auto_resolve, raise_finding

# ---------------------------------------------------------------------------
# Circuit breaker (P15-1)
# ---------------------------------------------------------------------------

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


@dataclass
class BreakerState:
    state: str = CLOSED
    failures: int = 0
    opened_at: dt.datetime | None = None
    successes_in_half_open: int = 0


class CircuitBreaker:
    """Per-provider circuit breaker with a half-open probe.

    Fails *fast* once a provider is known bad. The alternative — every request
    waiting out a 60-second timeout — turns a provider incident into an outage of
    your own, which is precisely the "governance tool became the outage" failure
    mode we refuse to cause (NFR-2).

    Process-local by design: this protects *this* worker's latency budget. A
    cluster-wide breaker needs shared state and is a Tranche-3 concern.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        half_open_successes: int = 2,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.half_open_successes = half_open_successes
        self._states: dict[str, BreakerState] = {}
        self._lock = threading.Lock()

    def state_of(self, key: str) -> str:
        with self._lock:
            return self._peek(key).state

    def _peek(self, key: str) -> BreakerState:
        state = self._states.setdefault(key, BreakerState())
        if state.state == OPEN and state.opened_at is not None:
            elapsed = (utcnow() - state.opened_at).total_seconds()
            if elapsed >= self.recovery_seconds:
                # Probe rather than fully reopening: one bad recovery should not
                # re-flood a provider that is still degraded.
                state.state = HALF_OPEN
                state.successes_in_half_open = 0
        return state

    def allows(self, key: str) -> bool:
        with self._lock:
            return self._peek(key).state != OPEN

    def record_success(self, key: str) -> None:
        with self._lock:
            state = self._peek(key)
            if state.state == HALF_OPEN:
                state.successes_in_half_open += 1
                if state.successes_in_half_open >= self.half_open_successes:
                    self._states[key] = BreakerState()
            else:
                state.failures = 0

    def record_failure(self, key: str) -> None:
        with self._lock:
            state = self._peek(key)
            state.failures += 1
            if state.state == HALF_OPEN or state.failures >= self.failure_threshold:
                state.state = OPEN
                state.opened_at = utcnow()
                state.successes_in_half_open = 0

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._states.clear()
            else:
                self._states.pop(key, None)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                key: {
                    "state": self._peek(key).state,
                    "failures": self._peek(key).failures,
                    "opened_at": (
                        self._peek(key).opened_at.isoformat() if self._peek(key).opened_at else None
                    ),
                }
                for key in list(self._states)
            }


#: Shared across enforcers in a process — the point is that one worker learns from
#: its own failures rather than each request rediscovering the outage.
BREAKER = CircuitBreaker()


# ---------------------------------------------------------------------------
# Fallback ladder (P15-2)
# ---------------------------------------------------------------------------


@dataclass
class Rung:
    """One step on the degradation ladder."""

    provider: str
    model: str
    note: str = ""


@dataclass
class FallbackLadder:
    """Ordered degradation path: preferred first, cheapest/most-available last.

    Degrading to a smaller model is a *governance* event, not just an ops one — the
    answer the user received did not come from the model the agent was evaluated
    against, and an evaluation baseline that silently covers a different model is
    worthless. So every degradation is recorded on the decision.
    """

    rungs: list[Rung] = field(default_factory=list)

    @classmethod
    def parse(cls, spec: list[str] | None) -> FallbackLadder:
        """From ``["openai:gpt-4o", "openai:gpt-4o-mini", "echo:echo-1"]``."""
        rungs = []
        for entry in spec or []:
            provider, _, model = entry.partition(":")
            rungs.append(Rung(provider=provider, model=model or "default"))
        return cls(rungs=rungs)

    def candidates(self, preferred: Rung | None = None) -> list[Rung]:
        return ([preferred] if preferred else []) + list(self.rungs)


@dataclass
class ProviderAttempt:
    provider: str
    model: str
    ok: bool
    error: str = ""
    breaker_state: str = CLOSED


@dataclass
class DegradationRecord:
    """What actually happened, for the trace and the decision."""

    attempts: list[ProviderAttempt] = field(default_factory=list)
    served_by: str | None = None
    degraded: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "served_by": self.served_by,
            "degraded": self.degraded,
            "attempts": [
                {
                    "provider": a.provider,
                    "model": a.model,
                    "ok": a.ok,
                    "error": a.error[:200],
                    "breaker": a.breaker_state,
                }
                for a in self.attempts
            ],
        }


# ---------------------------------------------------------------------------
# Budgets (P15-3, P15-5)
# ---------------------------------------------------------------------------

WINDOWS = {"minute": 60, "hour": 3600, "day": 86400}


@dataclass
class BudgetVerdict:
    exceeded: bool = False
    dimensions: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "exceeded": self.exceeded,
            "exceeded_dimensions": self.dimensions,
            "reason": self.reason,
            **self.usage,
        }


def _roll_window(budget: Budget) -> bool:
    """Reset counters when the window has elapsed. Returns True if it rolled."""
    seconds = WINDOWS.get(budget.window, 3600)
    started = budget.window_started_at
    if started is None:
        budget.window_started_at = utcnow()
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=dt.UTC)
    if (utcnow() - started).total_seconds() < seconds:
        return False
    budget.window_started_at = utcnow()
    budget.calls = 0
    budget.tokens = 0
    budget.cost_usd = 0.0
    return True


def check_budget(session: Session, scope_type: str, scope_id: str) -> BudgetVerdict:
    """Evaluate every budget dimension for a scope. Hard caps, not advisory."""
    budget = session.scalar(
        select(Budget).where(Budget.scope_type == scope_type, Budget.scope_id == scope_id)
    )
    if budget is None:
        return BudgetVerdict()

    if _roll_window(budget):
        # The condition that raised the finding no longer holds: the counters that
        # were over their caps have just been reset.
        auto_resolve(
            session,
            type="budget_exhausted",
            subject_type=scope_type,
            subject_id=scope_id,
            note=f"budget window ({budget.window}) rolled; usage counters reset",
        )
    exceeded: list[str] = []
    if budget.max_calls is not None and budget.calls >= budget.max_calls:
        exceeded.append("calls")
    if budget.max_tokens is not None and budget.tokens >= budget.max_tokens:
        exceeded.append("tokens")
    if budget.max_cost_usd is not None and budget.cost_usd >= budget.max_cost_usd:
        exceeded.append("cost")

    usage = {
        "window": budget.window,
        "calls": budget.calls,
        "tokens": budget.tokens,
        "cost_usd": round(budget.cost_usd, 6),
        "max_calls": budget.max_calls,
        "max_tokens": budget.max_tokens,
        "max_cost_usd": budget.max_cost_usd,
    }
    reason = ""
    if exceeded:
        parts = []
        for dimension in exceeded:
            used = usage.get(dimension if dimension != "cost" else "cost_usd")
            cap = usage.get(f"max_{dimension}" if dimension != "cost" else "max_cost_usd")
            parts.append(f"{dimension} {used}/{cap}")
        reason = (
            f"budget exhausted for {scope_type} '{scope_id}' this {budget.window}: "
            + ", ".join(parts)
        )
    return BudgetVerdict(exceeded=bool(exceeded), dimensions=exceeded, usage=usage, reason=reason)


def charge(
    session: Session,
    scope_type: str,
    scope_id: str,
    *,
    calls: int = 1,
    tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    budget = session.scalar(
        select(Budget).where(Budget.scope_type == scope_type, Budget.scope_id == scope_id)
    )
    if budget is None:
        return
    _roll_window(budget)
    budget.calls += calls
    budget.tokens += tokens
    budget.cost_usd += cost_usd
    session.flush()


def raise_budget_finding(
    session: Session, scope_type: str, scope_id: str, verdict: BudgetVerdict
) -> Finding | None:
    """A budget breach is a governed event, not just a 429.

    Deduplicated per window so an exhausted agent does not generate a finding per
    request — a finding queue nobody can read is a finding queue nobody reads.
    """
    if not verdict.exceeded:
        return None
    # One finding per exhausted scope, counted per refused request. It is closed when
    # the window rolls (see `check_budget`), so the next breach reopens it as a
    # recurrence instead of being hidden behind a finding from a window long gone.
    finding, _created = raise_finding(
        session,
        type="budget_exhausted",
        severity="high",
        title=f"Budget exhausted for {scope_type} '{scope_id}'",
        subject_type=scope_type,
        subject_id=scope_id,
        evidence=verdict.to_json(),
        control_keys=["NOM-RTG-08"],
    )
    return finding
