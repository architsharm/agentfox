"""What the governance layer does when it cannot do its job.

Two ways an inline control fails to run: it is broken, or it is saturated. Both end
with a request arriving that nobody checked, and the interesting question is not which
of "fail open" or "fail closed" is correct — it is that stating the choice as a global
switch is what makes both answers wrong.

**Fail closed everywhere** makes the governance layer a single point of failure for the
customer's product. The first time a detector times out, refunds stop working. Teams
respond by routing around the proxy, and a control that gets routed around is worse
than one that was never installed, because the architecture diagram still shows it.

**Fail open everywhere** is the option everyone picks, and it is worse. A control that
fails open silently is indistinguishable, from the outside, from a control that is
working — the same traffic flows, the same 200s come back, and the dashboards are
green because the detector that would have raised the finding is the one that is down.

So the position taken here is that fail-open is legitimate, and it must be **visible,
bounded, and impossible for some controls**:

* **Visible.** Every fail-open decision writes a degradation record. An ungoverned
  request that leaves no trace is the one nobody can go back and re-examine after the
  incident, and re-examining them is the entire reason to allow it.
* **Bounded.** Open converts to closed after a declared time or share of traffic. A
  control that has been open for an hour is not a degraded control, it is an absent
  one, and the system should stop pretending otherwise.
* **Impossible, for some.** Tenant isolation and entitlement filtering cannot be
  configured to fail open at all. Their failure mode is a data breach, and "we allowed
  it because the check was down" is not a sentence anyone wants to read out. The
  constructor refuses rather than the runtime warning.

Saturation is the same problem wearing a different hat, with one addition that is
usually got backwards. When load exceeds what can be governed, the thing to shed is
**work, not governance**. Putting the rate limiter in front of the guardrail means
overload produces ungoverned traffic — precisely when the system is least able to cope
with a mistake. Admission control here refuses the request outright; it never admits it
past the checks.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# --- Fail modes ------------------------------------------------------------

OPEN = "open"
CLOSED = "closed"

#: Controls whose failure mode is a disclosure rather than an outage. These may not be
#: configured to fail open under any policy — the enforcement is in the constructor,
#: not a warning at runtime, because a setting that can be changed under pressure at
#: three in the morning is not a guarantee.
NEVER_OPEN = (
    "tenant_isolation",
    "entitlement_filter",
    "data_access_scope",
    "audit_chain",
)


class UnsafeFailMode(ValueError):
    """Raised when a control that must never fail open is declared open."""


@dataclass(frozen=True)
class FailPolicy:
    """What to do when one control cannot run.

    ``max_open_seconds`` and ``max_open_fraction`` are the two ways a degradation stops
    being temporary. Both default to something short: the useful behaviour of fail-open
    is to survive a blip, and a blip that lasts ten minutes was an outage.
    """

    control: str
    on_unavailable: str = CLOSED
    max_open_seconds: int = 120
    max_open_fraction: float = 0.05
    #: Requests seen in the rolling window, used to evaluate the fraction.
    window_seconds: int = 300

    def __post_init__(self) -> None:
        if self.on_unavailable not in (OPEN, CLOSED):
            raise ValueError(f"fail mode must be '{OPEN}' or '{CLOSED}'")
        if self.on_unavailable == OPEN and self.control in NEVER_OPEN:
            raise UnsafeFailMode(
                f"'{self.control}' cannot be configured to fail open: its failure mode "
                "is a disclosure, not an outage, and 'we allowed it because the check "
                "was down' is not a defensible answer"
            )


@dataclass
class Degradation:
    """One request that ran without a control, and why."""

    control: str
    verdict: str
    reason: str
    at: dt.datetime
    error: str = ""
    escalated: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "verdict": self.verdict,
            "reason": self.reason,
            "at": self.at.isoformat(),
            "error": self.error,
            "escalated": self.escalated,
        }


class DegradationLedger:
    """Rolling memory of which controls have been unavailable, and for how long.

    Kept here rather than derived from the audit chain because the decision it feeds —
    "has this been open too long?" — has to be made on the request path, and reading
    the chain to answer it would put a database round-trip inside the thing that is
    already failing.
    """

    def __init__(self, *, window_seconds: int = 300) -> None:
        self.window = dt.timedelta(seconds=window_seconds)
        self._events: dict[str, deque[Degradation]] = {}
        self._requests: deque[dt.datetime] = deque()
        self._first_open: dict[str, dt.datetime] = {}

    def _expire(self, now: dt.datetime) -> None:
        cutoff = now - self.window
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()
        for events in self._events.values():
            while events and events[0].at < cutoff:
                events.popleft()

    def observe_request(self, now: dt.datetime | None = None) -> None:
        """Count a request that reached the governance layer, degraded or not.

        The denominator has to include the healthy traffic or the fraction is
        meaningless — five degraded requests out of five is an outage and five out of
        fifty thousand is a blip.
        """
        now = now or dt.datetime.now(dt.UTC)
        self._expire(now)
        self._requests.append(now)

    def record(self, event: Degradation) -> None:
        self._events.setdefault(event.control, deque()).append(event)
        self._first_open.setdefault(event.control, event.at)

    def clear(self, control: str) -> None:
        """A control that has recovered stops accumulating against its budget."""
        self._first_open.pop(control, None)
        self._events.pop(control, None)

    def open_seconds(self, control: str, now: dt.datetime) -> float:
        started = self._first_open.get(control)
        return (now - started).total_seconds() if started else 0.0

    def open_fraction(self, control: str, now: dt.datetime) -> float:
        self._expire(now)
        total = len(self._requests)
        if not total:
            return 0.0
        return len(self._events.get(control, ())) / total

    def degraded(self, now: dt.datetime | None = None) -> dict[str, dict[str, Any]]:
        """A single consistent snapshot of what is currently not being checked.

        Expiry happens once, up front. Reading it per control inside a comprehension
        made the answer depend on how far through the loop the reader was: one call
        reported unhealthy while listing nothing, and the next call reported healthy.
        A status view that changes what it says because you looked at it is worse than
        no status view.
        """
        now = now or dt.datetime.now(dt.UTC)
        self._expire(now)
        total = len(self._requests)
        return {
            control: {
                "open_seconds": round(self.open_seconds(control, now), 1),
                "open_fraction": round(len(events) / total, 4) if total else 0.0,
                "events": len(events),
            }
            for control, events in self._events.items()
            if events
        }

    def history(self, control: str | None = None) -> list[Degradation]:
        if control is not None:
            return list(self._events.get(control, ()))
        return sorted((e for events in self._events.values() for e in events), key=lambda e: e.at)


def service_fallback(
    control: str,
    error: str,
    *,
    policy: FailPolicy,
    ledger: DegradationLedger,
    now: dt.datetime | None = None,
) -> Degradation:
    """Decide what happens to this request now that ``control`` cannot run.

    Always returns a :class:`Degradation`, including when the answer is to block. The
    record is the point: an ungoverned request that leaves no trace is the one nobody
    can re-examine after the incident, and re-examining them is the entire reason to
    allow any of them through.
    """
    now = now or dt.datetime.now(dt.UTC)

    if policy.on_unavailable == CLOSED:
        event = Degradation(
            control,
            "block",
            f"'{control}' is unavailable and is declared fail-closed",
            now,
            error,
        )
        ledger.record(event)
        return event

    open_for = ledger.open_seconds(control, now)
    fraction = ledger.open_fraction(control, now)

    if open_for > policy.max_open_seconds:
        event = Degradation(
            control,
            "block",
            f"'{control}' has been failing open for {open_for:.0f}s, past its "
            f"{policy.max_open_seconds}s budget. A control open this long is not "
            "degraded, it is absent",
            now,
            error,
            escalated=True,
        )
        ledger.record(event)
        return event

    if fraction > policy.max_open_fraction:
        event = Degradation(
            control,
            "block",
            f"'{control}' has failed open on {fraction:.0%} of recent requests, past "
            f"its {policy.max_open_fraction:.0%} budget",
            now,
            error,
            escalated=True,
        )
        ledger.record(event)
        return event

    event = Degradation(
        control,
        "allow",
        f"'{control}' is unavailable and is declared fail-open; this request was not "
        "checked and is recorded so it can be re-examined",
        now,
        error,
    )
    ledger.record(event)
    return event


# --- Admission control -----------------------------------------------------

#: Higher is more important. Interactive traffic has a person waiting; batch work does
#: not, and shedding it costs a retry rather than a conversation.
PRIORITY = {"batch": 0, "background": 1, "normal": 2, "interactive": 3, "operator": 4}


@dataclass
class Admission:
    """Whether this request may enter the governance layer at all."""

    admitted: bool
    reason: str = ""
    retry_after_seconds: float = 0.0
    queue_depth: int = 0

    @property
    def verdict(self) -> str:
        return "allow" if self.admitted else "shed"

    def to_json(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "verdict": self.verdict,
            "reason": self.reason,
            "retry_after_seconds": self.retry_after_seconds,
            "queue_depth": self.queue_depth,
        }


@dataclass
class _Bucket:
    tokens: float
    updated: dt.datetime


class AdmissionController:
    """Rate limit and shed load — in front of the work, behind the governance.

    The ordering is the whole design. A limiter placed in front of the guardrails means
    that under overload the system's response is to stop checking things, which is the
    exact moment it can least afford a mistake. Here a shed request is *refused*: it
    never reaches the tool, and it never reaches the model either. The caller gets a
    retry-after and nothing happened.

    Shedding is by priority, lowest first, so a saturated system keeps answering the
    person who is waiting and drops the overnight backfill.
    """

    def __init__(
        self,
        *,
        rate_per_second: float = 50.0,
        burst: int = 100,
        max_concurrent: int = 64,
        shed_below_priority: str = "normal",
    ) -> None:
        self.rate = rate_per_second
        self.burst = burst
        self.max_concurrent = max_concurrent
        self.shed_below = PRIORITY.get(shed_below_priority, 2)
        self._buckets: dict[str, _Bucket] = {}
        self._in_flight = 0

    def _take(self, scope: str, now: dt.datetime) -> bool:
        bucket = self._buckets.get(scope)
        if bucket is None:
            bucket = _Bucket(float(self.burst), now)
            self._buckets[scope] = bucket
        elapsed = (now - bucket.updated).total_seconds()
        bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rate)
        bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    def admit(
        self,
        *,
        scope: str = "default",
        priority: str = "normal",
        now: dt.datetime | None = None,
    ) -> Admission:
        now = now or dt.datetime.now(dt.UTC)
        rank = PRIORITY.get(priority, 2)

        if self._in_flight >= self.max_concurrent:
            # Concurrency is the hard ceiling: past it, latency grows without bound and
            # the governance checks are what starts timing out. Operator traffic is
            # exempt because the kill switch has to work when the system is saturated.
            if rank < PRIORITY["operator"]:
                return Admission(
                    False,
                    f"{self._in_flight} requests already in flight, at the "
                    f"{self.max_concurrent} ceiling. Refused rather than admitted "
                    "unchecked",
                    retry_after_seconds=1.0,
                    queue_depth=self._in_flight,
                )

        if not self._take(scope, now):
            if rank <= self.shed_below:
                return Admission(
                    False,
                    f"'{scope}' is over its rate limit and '{priority}' traffic is shed "
                    "first — nobody is waiting on it",
                    retry_after_seconds=max(1.0 / self.rate, 0.05),
                    queue_depth=self._in_flight,
                )
            if rank < PRIORITY["operator"]:
                return Admission(
                    False,
                    f"'{scope}' is over its rate limit",
                    retry_after_seconds=max(1.0 / self.rate, 0.05),
                    queue_depth=self._in_flight,
                )

        return Admission(True, queue_depth=self._in_flight)

    def enter(self) -> None:
        self._in_flight += 1

    def leave(self) -> None:
        self._in_flight = max(0, self._in_flight - 1)

    @property
    def in_flight(self) -> int:
        return self._in_flight


#: The process-wide admission gate. Lazily built from settings, unlike
#: `reliability.BREAKER`'s fixed-default construction at import time — these limits
#: are exactly the ones an operator is expected to size to their own deployment
#: (`NOMETRIA_ADMISSION_*`), and building it at import time would freeze in
#: whatever settings happened to be current then, which is wrong for anything that
#: overrides them afterwards (every test in this suite included).
_ADMISSION: AdmissionController | None = None


def get_admission_controller() -> AdmissionController:
    global _ADMISSION
    if _ADMISSION is None:
        from agentfox.core.config import get_settings

        settings = get_settings()
        _ADMISSION = AdmissionController(
            rate_per_second=settings.admission_rate_per_second,
            burst=settings.admission_burst,
            max_concurrent=settings.admission_max_concurrent,
            shed_below_priority=settings.admission_shed_below_priority,
        )
    return _ADMISSION


def reset_admission_controller() -> None:
    """Test-only: drop the singleton so the next call rebuilds it from current
    settings and with empty state — mirrors `db.reset_engine`. Without this, one
    test's rate-limit consumption or in-flight count would bleed into the next."""
    global _ADMISSION
    _ADMISSION = None


def health(ledger: DegradationLedger, *, now: dt.datetime | None = None) -> dict[str, Any]:
    """What is currently not being checked.

    Written for the status endpoint rather than the request path. "Healthy" here means
    every control is running — not that requests are succeeding, which is the number a
    fail-open system will happily report while checking nothing.
    """
    degraded = ledger.degraded(now)
    return {
        "healthy": not degraded,
        "degraded_controls": degraded,
        "note": (
            "healthy means every control ran, not that requests succeeded — a "
            "fail-open system reports success while checking nothing"
        ),
    }


# --- Service-level degradation (gap 0.7) -----------------------------------
#
# Everything above this line is per *control*: one detector timed out, so this one
# request went unchecked. That is the wrong granularity for the failure that actually
# takes a deployment down. When the detector pipeline as a whole has nothing available
# to run, when the policy engine's OPA sidecar is unreachable, when the database is
# refusing connections, or when the configured model provider is gone, every request
# is ungoverned — and `policy/store.py::get_engine` silently substituting the native
# engine for an unreachable OPA is exactly the invisible-fail-open this module's
# docstring refuses to accept. The probes below name those four dependencies, run the
# declared `FailPolicy` against them, and put the answer somewhere an operator can
# read it.

#: The dependencies a `/v1/*` request needs before it can be governed at all.
DETECTOR_PIPELINE = "detector_pipeline"
POLICY_ENGINE = "policy_engine"
DATABASE = "database"
MODEL_PROVIDER = "model_provider"

SERVICES = (DETECTOR_PIPELINE, POLICY_ENGINE, DATABASE, MODEL_PROVIDER)


def service_policy(service: str, *, fail_mode: str | None = None) -> FailPolicy:
    """The `FailPolicy` for one service, from `NOMETRIA_FAIL_MODE`.

    The open/closed decision is the operator's declared `fail_mode` and nothing else —
    but it is run through `FailPolicy`'s constructor rather than applied directly, so
    the `NEVER_OPEN` rule keeps enforcing itself. If a service is ever named after a
    control whose failure mode is a disclosure, `UnsafeFailMode` fires here and it
    fails closed regardless of what the setting says, which is the whole point of
    encoding that rule in the constructor instead of at each call site.
    """
    from agentfox.core.config import get_settings

    try:
        mode = (fail_mode or get_settings().fail_mode or CLOSED).strip().lower()
    except Exception:  # settings unreadable is itself a degradation; assume the worst
        mode = CLOSED
    try:
        return FailPolicy(service, mode)
    except (UnsafeFailMode, ValueError):
        return FailPolicy(service, CLOSED)


#: Process-level, for the same reason `DegradationLedger` exists at all: the question
#: "has this been open too long?" is asked on the request path, and answering it from
#: the audit chain would put a database round-trip inside the thing that is already
#: failing. Lazily built so a test's settings changes are picked up, exactly like
#: `_ADMISSION` above.
_LEDGER: DegradationLedger | None = None


def get_degradation_ledger() -> DegradationLedger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = DegradationLedger()
    return _LEDGER


def reset_degradation_ledger() -> None:
    """Test-only: drop the ledger so one test's recorded outage does not bleed into
    the next. Mirrors `reset_admission_controller`."""
    global _LEDGER, _PROBE_CACHE
    _LEDGER = None
    _PROBE_CACHE = {}


# --- Probes ----------------------------------------------------------------
#
# Each returns an error string when the dependency is unavailable, or "" when it is
# fine. Each is individually wrapped by `probe_services`: a probe that throws is
# itself evidence the dependency is unwell, never a 500 for the caller.


def _probe_detector_pipeline() -> str:
    """Not "a detector failed" — that is already handled per-detector. This is the
    pipeline having nothing at all it can run, so every request goes unchecked."""
    from agentfox.core.config import get_settings
    from agentfox.detection import available_detectors

    enabled = set(get_settings().enabled_detectors)
    if not enabled:
        return "no detectors are enabled"
    live = set(available_detectors())
    if not (enabled & live):
        return (
            f"none of the {len(enabled)} enabled detectors is available "
            f"({', '.join(sorted(enabled))}) — the pipeline has nothing to run"
        )
    return ""


def _probe_policy_engine() -> str:
    """A remote OPA that is unreachable is the dangerous case.

    `policy/store.py::get_engine` already falls back to the native engine so the
    customer's agent keeps working — correct, and completely silent. The fallback is
    a different engine evaluating the request than the one the deployment declared,
    which is a governance event, not an ops detail.
    """
    from agentfox.core.config import get_settings

    settings = get_settings()
    if settings.policy_engine != "opa":
        return ""
    from agentfox.policy.opa import OpaPolicyEngine

    if not OpaPolicyEngine().available():
        return (
            f"OPA at {settings.opa_url} is unreachable; policy is being evaluated by "
            "the native engine instead of the one this deployment declared"
        )
    return ""


def _probe_database() -> str:
    """Beyond the request's own session — the request's session proves only that one
    checked-out connection is alive, which is the one case that never needed proving.
    """
    from sqlalchemy import text

    from agentfox.core.db import session_scope

    with session_scope() as probe:
        probe.execute(text("SELECT 1"))
    return ""


def _probe_model_provider() -> str:
    from agentfox.core.config import get_settings
    from agentfox.providers import available_providers

    configured = get_settings().default_provider
    if configured not in available_providers():
        return f"the configured model provider '{configured}' reports unavailable"
    return ""


_PROBES = {
    DETECTOR_PIPELINE: _probe_detector_pipeline,
    POLICY_ENGINE: _probe_policy_engine,
    DATABASE: _probe_database,
    MODEL_PROVIDER: _probe_model_provider,
}

#: service -> (checked_at, error). A probe costs a database round-trip and, with a
#: remote OPA, an HTTP call; paying that per request would make this module the
#: latency problem it exists to prevent.
_PROBE_CACHE: dict[str, tuple[dt.datetime, str]] = {}


def probe_services(*, now: dt.datetime | None = None, force: bool = False) -> dict[str, str]:
    """Which dependencies are currently unhealthy, as ``{service: error}``.

    Results are cached for `service_probe_interval_seconds`; `force` skips the cache
    for the status endpoints, where an operator asking "is it up *now*" should not be
    told what was true five seconds ago.
    """
    from agentfox.core.config import get_settings

    now = now or dt.datetime.now(dt.UTC)
    try:
        ttl = dt.timedelta(seconds=float(get_settings().service_probe_interval_seconds))
    except Exception:
        ttl = dt.timedelta(seconds=5)

    errors: dict[str, str] = {}
    for service, probe in _PROBES.items():
        cached = _PROBE_CACHE.get(service)
        if not force and cached is not None and now - cached[0] < ttl:
            error = cached[1]
        else:
            try:
                error = probe() or ""
            except Exception as exc:
                # A probe that throws is evidence about the dependency, not a bug to
                # propagate: an unreachable database raises here rather than returning.
                error = f"{type(exc).__name__}: {exc}"
            _PROBE_CACHE[service] = (now, error)
        if error:
            errors[service] = error
    return errors


def check_services(*, now: dt.datetime | None = None, force: bool = False) -> list[Degradation]:
    """Probe every dependency, record what is down, and return the verdicts.

    Never raises. A ledger that can break a request is worse than no ledger: the whole
    argument for allowing fail-open is that it is *recorded*, and a recorder that takes
    the request down with it has turned a degradation into an outage.
    """
    events: list[Degradation] = []
    try:
        now = now or dt.datetime.now(dt.UTC)
        ledger = get_degradation_ledger()
        errors = probe_services(now=now, force=force)
        for service in SERVICES:
            error = errors.get(service)
            if not error:
                ledger.clear(service)  # recovered: the clock restarts
                continue
            events.append(
                service_fallback(
                    service, error, policy=service_policy(service), ledger=ledger, now=now
                )
            )
    except Exception:  # pragma: no cover - the ledger must never break a request
        log.warning("service degradation check failed; request proceeds", exc_info=True)
        return []
    return events


def observe_governed_request(now: dt.datetime | None = None) -> None:
    """Count a request against the ledger's denominator. Never raises."""
    try:
        get_degradation_ledger().observe_request(now)
    except Exception:  # pragma: no cover
        log.warning("could not count request against the degradation ledger", exc_info=True)


def service_health(*, now: dt.datetime | None = None, probe: bool = True) -> dict[str, Any]:
    """The operator surface for gap 0.7 — what is currently not being checked.

    Carries `fail_mode` because "degraded" means something different under each: open
    means those requests are being served unchecked, closed means they are being
    refused, and a status view that does not say which is not telling an operator what
    is happening to their traffic.
    """
    from agentfox.core.config import get_settings

    try:
        ledger = get_degradation_ledger()
        # Deliberately read-only: this probes and reports, and never calls
        # `service_fallback`. An earlier version recorded what it found, which meant
        # that opening the dashboard pushed a fail-open control closer to its
        # `max_open_fraction` budget — a status view that changes the system by being
        # read, which is the failure this module's own docstring objects to.
        errors = probe_services(now=now, force=True) if probe else {}
        status = health(ledger, now=now)
        try:
            mode = get_settings().fail_mode
        except Exception:
            mode = "unknown"
        return {
            **status,
            # Down *now*, from a fresh probe.
            "healthy": bool(status.get("healthy")) and not errors,
            "fail_mode": mode,
            "services": sorted(SERVICES),
            "unavailable": {
                service: {
                    "error": error,
                    "policy": service_policy(service).on_unavailable,
                }
                for service, error in sorted(errors.items())
            },
            # What the request path actually recorded — the ungoverned requests that
            # can be gone back over after the incident, which is the entire reason
            # fail-open is allowed at all.
            "recorded": {
                service: events[-1].to_json()
                for service in SERVICES
                if (events := ledger.history(service))
            },
        }
    except Exception:  # pragma: no cover - a status view must not 500
        log.warning("could not build service health", exc_info=True)
        return {"healthy": None, "degraded_controls": {}, "error": "health unavailable"}
