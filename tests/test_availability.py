"""What the governance layer does when it cannot do its job.

Two ways an inline control fails to run: it is broken, or it is saturated. Both end
with a request arriving that nobody checked. The tests here are built around the
position that fail-open is legitimate and must be visible, bounded, and impossible for
some controls — because a control that fails open silently is indistinguishable, from
the outside, from one that is working.
"""

from __future__ import annotations

import datetime as dt

import pytest

from agentfox.runtime.availability import (
    CLOSED,
    NEVER_OPEN,
    OPEN,
    AdmissionController,
    DegradationLedger,
    FailPolicy,
    UnsafeFailMode,
    get_admission_controller,
    health,
    reset_admission_controller,
    service_fallback,
)

T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.fixture
def ledger():
    led = DegradationLedger()
    for _ in range(100):
        led.observe_request(T0)
    return led


# --- Fail closed -----------------------------------------------------------


def test_a_fail_closed_control_blocks_and_says_why(ledger):
    event = service_fallback(
        "pii_detection",
        "detector timeout",
        policy=FailPolicy("pii_detection", CLOSED),
        ledger=ledger,
        now=T0,
    )
    assert event.verdict == "block"
    assert "fail-closed" in event.reason


# --- Fail open, visibly ----------------------------------------------------


def test_a_fail_open_request_is_allowed_and_recorded(ledger):
    """An ungoverned request that leaves no trace is the one nobody can re-examine
    after the incident, and re-examining them is the entire reason to allow it."""
    event = service_fallback(
        "pii_detection",
        "detector timeout",
        policy=FailPolicy("pii_detection", OPEN),
        ledger=ledger,
        now=T0,
    )
    assert event.verdict == "allow"
    assert ledger.history("pii_detection") == [event]
    assert "recorded so it can be re-examined" in event.reason


def test_blocking_is_recorded_too(ledger):
    """The record is the point, not the verdict."""
    service_fallback(
        "pii_detection",
        "boom",
        policy=FailPolicy("pii_detection", CLOSED),
        ledger=ledger,
        now=T0,
    )
    assert len(ledger.history("pii_detection")) == 1


# --- Fail open, boundedly --------------------------------------------------


def test_open_converts_to_closed_once_it_has_lasted_too_long(ledger):
    """A control open for an hour is not a degraded control, it is an absent one, and
    the system should stop pretending otherwise."""
    policy = FailPolicy("pii_detection", OPEN, max_open_seconds=120)
    service_fallback("pii_detection", "boom", policy=policy, ledger=ledger, now=T0)

    later = T0 + dt.timedelta(seconds=300)
    ledger.observe_request(later)
    event = service_fallback("pii_detection", "boom", policy=policy, ledger=ledger, now=later)
    assert event.verdict == "block"
    assert event.escalated
    assert "not degraded, it is absent" in event.reason


def test_open_converts_to_closed_once_it_covers_too_much_traffic():
    led = DegradationLedger()
    policy = FailPolicy("pii_detection", OPEN, max_open_seconds=10_000, max_open_fraction=0.05)
    for _ in range(10):
        led.observe_request(T0)
    verdicts = [
        service_fallback("pii_detection", "boom", policy=policy, ledger=led, now=T0).verdict
        for _ in range(4)
    ]
    assert verdicts[0] == "allow"
    assert verdicts[-1] == "block", "past 5% of a 10-request window"


def test_the_denominator_includes_healthy_traffic():
    """Five degraded requests out of five is an outage; five out of fifty thousand is a
    blip, and a fraction computed only over failures cannot tell them apart."""
    led = DegradationLedger()
    for _ in range(10_000):
        led.observe_request(T0)
    policy = FailPolicy("pii_detection", OPEN, max_open_seconds=10_000, max_open_fraction=0.05)
    for _ in range(5):
        event = service_fallback("pii_detection", "boom", policy=policy, ledger=led, now=T0)
    assert event.verdict == "allow"


def test_a_recovered_control_stops_accumulating_against_its_budget(ledger):
    policy = FailPolicy("pii_detection", OPEN, max_open_seconds=120)
    service_fallback("pii_detection", "boom", policy=policy, ledger=ledger, now=T0)
    ledger.clear("pii_detection")

    later = T0 + dt.timedelta(seconds=300)
    ledger.observe_request(later)
    event = service_fallback("pii_detection", "boom", policy=policy, ledger=ledger, now=later)
    assert event.verdict == "allow", "the clock restarts on recovery"


# --- Fail open, impossibly -------------------------------------------------


@pytest.mark.parametrize("control", NEVER_OPEN)
def test_some_controls_cannot_be_configured_to_fail_open(control):
    """Their failure mode is a disclosure, not an outage.

    Refused in the constructor rather than warned about at runtime, because a setting
    that can be changed under pressure at three in the morning is not a guarantee.
    """
    with pytest.raises(UnsafeFailMode):
        FailPolicy(control, OPEN)


def test_those_controls_can_still_be_declared_fail_closed():
    assert FailPolicy("tenant_isolation", CLOSED).on_unavailable == CLOSED


def test_an_unknown_fail_mode_is_rejected():
    with pytest.raises(ValueError):
        FailPolicy("pii_detection", "maybe")


# --- Admission control -----------------------------------------------------


def test_a_shed_request_is_refused_not_admitted_unchecked():
    """The ordering is the whole design. A limiter in front of the guardrails means
    overload makes the system stop checking things."""
    controller = AdmissionController(rate_per_second=10, burst=1, max_concurrent=10)
    assert controller.admit(now=T0).admitted
    shed = controller.admit(now=T0)
    assert not shed.admitted
    assert shed.verdict == "shed"
    assert shed.retry_after_seconds > 0


def test_batch_traffic_is_shed_before_interactive():
    """A saturated system keeps answering the person who is waiting and drops the
    overnight backfill."""
    controller = AdmissionController(rate_per_second=1, burst=1, max_concurrent=10)
    controller.admit(priority="batch", now=T0)
    batch = controller.admit(priority="batch", now=T0)
    assert not batch.admitted
    assert "shed first" in batch.reason


def test_operator_traffic_survives_saturation():
    """The kill switch has to work when the system is saturated."""
    controller = AdmissionController(rate_per_second=1, burst=0, max_concurrent=1)
    controller.enter()
    assert controller.admit(priority="interactive", now=T0).verdict == "shed"
    assert controller.admit(priority="operator", now=T0).admitted


def test_the_concurrency_ceiling_is_hard():
    controller = AdmissionController(rate_per_second=1000, burst=1000, max_concurrent=2)
    controller.enter()
    controller.enter()
    result = controller.admit(priority="interactive", now=T0)
    assert not result.admitted
    assert result.queue_depth == 2


def test_tokens_refill_over_time():
    controller = AdmissionController(rate_per_second=10, burst=1, max_concurrent=10)
    controller.admit(now=T0)
    assert not controller.admit(now=T0).admitted
    assert controller.admit(now=T0 + dt.timedelta(seconds=1)).admitted


def test_scopes_are_limited_independently():
    """One tenant exhausting its budget must not shed another's traffic."""
    controller = AdmissionController(rate_per_second=1, burst=1, max_concurrent=10)
    controller.admit(scope="org-a", now=T0)
    assert not controller.admit(scope="org-a", now=T0).admitted
    assert controller.admit(scope="org-b", now=T0).admitted


def test_ordinary_load_is_admitted():
    """The false-positive floor: a limiter that sheds normal traffic is an outage."""
    controller = AdmissionController(rate_per_second=50, burst=100, max_concurrent=64)
    assert all(controller.admit(now=T0).admitted for _ in range(100))


# --- The singleton, and its wiring into the live gateway (P15-6) -----------
#
# `AdmissionController` itself was already fully tested above; what was missing
# — the finding in gap-analysis.md — is that nothing on the request path ever
# called it. These tests are about that wiring specifically, not the algorithm.


def test_get_admission_controller_reads_settings(monkeypatch):
    monkeypatch.setenv("NOMETRIA_ADMISSION_RATE_PER_SECOND", "5")
    monkeypatch.setenv("NOMETRIA_ADMISSION_BURST", "7")
    monkeypatch.setenv("NOMETRIA_ADMISSION_MAX_CONCURRENT", "9")
    from agentfox.core.config import reset_settings_cache

    reset_settings_cache()
    reset_admission_controller()
    try:
        controller = get_admission_controller()
        assert (controller.rate, controller.burst, controller.max_concurrent) == (5, 7, 9)
    finally:
        reset_settings_cache()
        reset_admission_controller()


def test_the_controller_is_a_singleton_until_reset():
    reset_admission_controller()
    try:
        first = get_admission_controller()
        assert get_admission_controller() is first
        reset_admission_controller()
        assert get_admission_controller() is not first
    finally:
        reset_admission_controller()


def _saturate_admission(monkeypatch) -> None:
    """One token, refilling too slowly for the test to ever see a second one."""
    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("NOMETRIA_ADMISSION_BURST", "1")
    monkeypatch.setenv("NOMETRIA_ADMISSION_RATE_PER_SECOND", "0.0001")
    reset_settings_cache()
    reset_admission_controller()


def test_the_gate_sheds_inline_traffic_once_saturated(client, monkeypatch):
    """The same shedding proven algorithmically above, now reachable from a live
    request — closing the "zero callers on the live request path" gap."""
    _saturate_admission(monkeypatch)
    payload = {"agent": "nobody", "content": "hi", "surface": "input"}

    first = client.post("/v1/guard/input", json=payload)
    assert first.status_code != 429

    shed = client.post("/v1/guard/input", json=payload)
    assert shed.status_code == 429
    assert shed.json()["error"]["type"] == "agentfox_admission_shed"
    assert float(shed.headers["Retry-After"]) >= 1


def test_the_gate_does_not_apply_to_the_control_plane(client, monkeypatch):
    """`/api/*` is operator traffic — out of scope for a budget sized for the
    inline surface an agent calls under load."""
    _saturate_admission(monkeypatch)
    client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})  # spend the token

    assert client.get("/api/health").status_code == 200


def test_ordinary_traffic_through_the_live_gate_is_never_shed(client):
    """False-positive floor for the wiring: default settings must not shed
    ordinary traffic through the real gateway."""
    for _ in range(5):
        resp = client.post("/v1/guard/input", json={"agent": "nobody", "content": "hi"})
        assert resp.status_code != 429


# --- Health ----------------------------------------------------------------


def test_health_means_every_control_ran_not_that_requests_succeeded(ledger):
    service_fallback(
        "pii_detection",
        "boom",
        policy=FailPolicy("pii_detection", OPEN),
        ledger=ledger,
        now=T0,
    )
    status = health(ledger, now=T0)
    assert not status["healthy"]
    assert "pii_detection" in status["degraded_controls"]


def test_reading_health_twice_gives_the_same_answer(ledger):
    """Expiry was evaluated per control inside the comprehension, so the answer
    depended on how far through the loop the reader was: one call reported unhealthy
    while listing nothing, and the next reported healthy."""
    service_fallback(
        "pii_detection",
        "boom",
        policy=FailPolicy("pii_detection", OPEN),
        ledger=ledger,
        now=T0,
    )
    assert health(ledger, now=T0) == health(ledger, now=T0)


def test_a_healthy_system_reports_nothing_degraded(ledger):
    assert health(ledger, now=T0)["healthy"]
