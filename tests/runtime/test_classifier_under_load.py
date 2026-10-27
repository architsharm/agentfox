"""The classifier under concurrency: batched, request-path first, nothing scored for
a caller that stopped waiting, and every check answered without it counted.

Measured on origin/main 6a082b77 (16 concurrent clients, one gateway process, cache
off): 58% of checks were answered without the classifier. The heavy pool (8 threads,
each blocked on the batcher) was the concurrency limit, the advisory backstop
model's passes ran after each response on the same device and slowed the
request-path passes 3-8x, and texts whose check had already timed out were still
scored. These tests pin the behaviour that fixed it, and that a degraded check is
never a silent pass.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from agentfox.capabilities.detection.base import BaseDetector
from agentfox.capabilities.detection.loading import (
    BatchedScorer,
    CallScope,
    InferenceAbandoned,
    InferenceScheduler,
    InferenceShed,
    background_inference,
    enter_scope,
)
from agentfox.capabilities.detection.pipeline import HEAVY_POOL_FACTOR, DetectorPipeline
from agentfox.runtime.availability import (
    CheckDegradationMeter,
    get_check_meter,
    reset_check_meter,
)


class _Pipe:
    """A stand-in model: records each pass, labels each text with itself, and can be
    held mid-pass so a test can queue work behind it."""

    def __init__(self, name: str = "m", delay: float = 0.0, log: list | None = None) -> None:
        self.name = name
        self.log = log if log is not None else []
        self.delay = delay
        self.passes: list[list[str]] = []
        self.hold = threading.Event()
        self.hold.set()
        self.entered = threading.Event()
        self.lock = threading.Lock()

    def __call__(self, texts, batch_size=None):
        self.entered.set()
        self.hold.wait(5)
        if self.delay:
            time.sleep(self.delay)
        with self.lock:
            self.passes.append(list(texts))
            self.log.append(self.name)
        return [[{"label": f"{self.name}:{t}", "score": 0.9}] for t in texts]


def _scorer(pipe, sched, **kw):
    return BatchedScorer(pipe, cache_size=0, scheduler=sched, **kw)


def _in_thread(fn, *args):
    box: dict = {}

    def run():
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


# --- batching ----------------------------------------------------------------


def test_concurrent_callers_share_passes_and_each_gets_its_own_rows():
    sched = InferenceScheduler()
    pipe = _Pipe(delay=0.02)
    scorer = _scorer(pipe, sched)
    pipe.hold.clear()
    first, first_box = _in_thread(scorer.score, ["t0"])
    assert pipe.entered.wait(2)
    # Queued behind the held pass: they go out together in the next one.
    threads = [_in_thread(scorer.score, [f"t{i}", f"t{i}b"]) for i in range(1, 8)]
    assert _wait_for(lambda: sched.pending()["request_path"] == 7)
    pipe.hold.set()
    for t, _box in [(first, first_box), *threads]:
        t.join(5)
    assert first_box["value"] == [[{"label": "m:t0", "score": 0.9}]]
    for i, (_t, box) in enumerate(threads, start=1):
        assert [row[0]["label"] for row in box["value"]] == [f"m:t{i}", f"m:t{i}b"]
    assert len(pipe.passes) == 2  # 15 texts in 2 passes, not 8
    assert sorted(pipe.passes[1]) == sorted(t for i in range(1, 8) for t in (f"t{i}", f"t{i}b"))


def test_a_batch_never_exceeds_max_batch_and_nothing_is_lost():
    sched = InferenceScheduler()
    pipe = _Pipe()
    scorer = _scorer(pipe, sched, max_batch=4)
    pipe.hold.clear()
    head = _in_thread(scorer.score, ["head"])
    assert pipe.entered.wait(2)
    threads = [_in_thread(scorer.score, [f"x{i}"]) for i in range(10)]
    assert _wait_for(lambda: sched.pending()["request_path"] == 10)
    pipe.hold.set()
    for t, _box in [head, *threads]:
        t.join(5)
    assert all(len(p) <= 4 for p in pipe.passes)
    assert sorted(t for p in pipe.passes for t in p) == sorted(
        ["head"] + [f"x{i}" for i in range(10)]
    )
    assert all("value" in box for _t, box in threads)


def test_passes_never_overlap_and_each_is_one_model():
    sched = InferenceScheduler()
    a, b = _Pipe("a", delay=0.005), _Pipe("b", delay=0.005)
    active = threading.Lock()
    overlapped: list[bool] = []
    sa, sb = _scorer(a, sched), _scorer(b, sched)
    for scorer in (sa, sb):
        inner = scorer._forward

        def forward(batch, _inner=inner):
            if not active.acquire(blocking=False):
                overlapped.append(True)
                return _inner(batch)
            try:
                return _inner(batch)
            finally:
                active.release()

        scorer._forward = forward  # type: ignore[method-assign]
    threads = [_in_thread((sa if i % 2 else sb).score, [f"t{i}"]) for i in range(16)]
    for t, _box in threads:
        t.join(5)
    assert not overlapped
    for i, (_t, box) in enumerate(threads):
        assert box["value"][0][0]["label"] == f"{'a' if i % 2 else 'b'}:t{i}"
    assert sorted(t for p in a.passes for t in p) == sorted(f"t{i}" for i in range(1, 16, 2))


# --- priority ----------------------------------------------------------------


def test_request_path_passes_go_before_background_ones():
    sched = InferenceScheduler()
    order: list[str] = []
    primary, backstop = _Pipe("primary", log=order), _Pipe("backstop", log=order)
    sp, sb = _scorer(primary, sched), _scorer(backstop, sched)

    primary.hold.clear()
    head = _in_thread(sp.score, ["first"])
    assert primary.entered.wait(2)

    def background_score():
        with background_inference():
            return sb.score(["advisory"])

    bg = _in_thread(background_score)
    assert _wait_for(lambda: sched.pending()["background"] == 1)
    urgent = _in_thread(sp.score, ["second"])  # queued after the background job
    assert _wait_for(lambda: sched.pending()["request_path"] == 1)
    primary.hold.set()
    for t, _box in (head, bg, urgent):
        t.join(5)
    assert order == ["primary", "primary", "backstop"]
    assert bg[1]["value"][0][0]["label"] == "backstop:advisory"


def test_background_work_past_its_backlog_is_refused_and_counted():
    sched = InferenceScheduler(max_background=1)
    pipe = _Pipe()
    scorer = _scorer(pipe, sched)
    pipe.hold.clear()
    head = _in_thread(scorer.score, ["busy"])
    assert pipe.entered.wait(2)

    def background_score(text):
        with background_inference():
            return scorer.score([text])

    queued = _in_thread(background_score, "one")
    assert _wait_for(lambda: sched.pending()["background"] == 1)
    with pytest.raises(InferenceShed):
        background_score("two")
    assert sched.stats["shed"] == 1
    pipe.hold.set()
    for t, _box in (head, queued):
        t.join(5)
    assert "value" in queued[1]


# --- a caller that stopped waiting -----------------------------------------------


def test_an_abandoned_call_is_never_scored_and_frees_its_thread():
    sched = InferenceScheduler()
    pipe = _Pipe()
    scorer = _scorer(pipe, sched)
    pipe.hold.clear()
    head = _in_thread(scorer.score, ["busy"])
    assert pipe.entered.wait(2)

    scope = CallScope()

    def scoped():
        enter_scope(scope)
        return scorer.score(["nobody waits for me"])

    import contextvars

    waiter = _in_thread(lambda: contextvars.copy_context().run(scoped))
    assert _wait_for(lambda: sched.pending()["request_path"] == 1)
    scope.abandon()
    waiter[0].join(1)
    assert not waiter[0].is_alive()  # released at once, not after the pass
    assert isinstance(waiter[1]["error"], InferenceAbandoned)
    pipe.hold.set()
    head[0].join(5)
    assert _wait_for(lambda: sched.stats["abandoned"] == 1)
    assert all("nobody waits for me" not in p for p in pipe.passes)


def test_a_call_past_its_deadline_stops_waiting_and_is_dropped():
    sched = InferenceScheduler()
    pipe = _Pipe()
    scorer = _scorer(pipe, sched)
    pipe.hold.clear()
    head = _in_thread(scorer.score, ["busy"])
    assert pipe.entered.wait(2)
    import contextvars

    def scoped():
        enter_scope(CallScope(time.perf_counter() + 0.05))
        return scorer.score(["too late"])

    started = time.perf_counter()
    with pytest.raises(InferenceAbandoned):
        contextvars.copy_context().run(scoped)
    assert time.perf_counter() - started < 0.5
    pipe.hold.set()
    head[0].join(5)
    _wait_for(lambda: not sched.pending()["request_path"])
    assert all("too late" not in p for p in pipe.passes)


class _ModelDetector(BaseDetector):
    """A pooled detector that scores through a batched scorer, as the classifier does."""

    key = "load.model"
    version = "1"
    surfaces = ("input",)
    timeout_ms = 60

    def __init__(self, scorer: BatchedScorer) -> None:
        self.scorer = scorer

    def available(self) -> bool:
        return True

    def _detect(self, content, context):
        self.scorer.score([content])
        return []


def test_a_pipeline_timeout_is_degraded_and_its_text_is_dropped_unscored():
    sched = InferenceScheduler()
    pipe = _Pipe()
    scorer = _scorer(pipe, sched)
    pipe.hold.clear()
    head = _in_thread(scorer.score, ["busy"])
    assert pipe.entered.wait(2)
    from agentfox.capabilities.detection.base import DetectionContext

    result = DetectorPipeline([_ModelDetector(scorer)], budget_ms=300).run(
        "the check's text", DetectionContext(surface="input")
    )
    assert result.degraded == ["load.model"]
    assert [r.status for r in result.results] == ["timeout"]
    pipe.hold.set()
    head[0].join(5)
    assert _wait_for(lambda: sched.stats["abandoned"] == 1)
    time.sleep(0.05)
    assert all("the check's text" not in p for p in pipe.passes)


def test_the_heavy_pool_is_larger_than_the_light_one():
    pipeline = DetectorPipeline([], max_workers=3)
    assert pipeline._pool._max_workers == 3
    assert pipeline._heavy_pool._max_workers == 3 * HEAVY_POOL_FACTOR


# --- the degradation meter ------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_meter_counts_checks_and_degraded_ones_by_detector_and_cause():
    meter = CheckDegradationMeter(min_checks=1)
    meter.observe({})
    meter.observe({"injection.classifier": "timeout"})
    meter.observe({"injection.classifier": "timeout", "custom.x": "error"})
    snap = meter.snapshot()
    assert (snap["checks_total"], snap["degraded_total"]) == (3, 2)
    assert snap["by_detector"] == [
        {"detector": "custom.x", "cause": "error", "count": 1},
        {"detector": "injection.classifier", "cause": "timeout", "count": 2},
    ]
    assert snap["window_ratio"] == round(2 / 3, 4)


def test_the_window_forgets_old_checks_but_the_totals_do_not():
    clock = _Clock()
    meter = CheckDegradationMeter(window_seconds=60, min_checks=1, clock=clock)
    for _ in range(4):
        meter.observe({"m": "timeout"})
    clock.now += 61
    meter.observe({})
    snap = meter.snapshot()
    assert (snap["window_checks"], snap["window_degraded"], snap["window_ratio"]) == (1, 0, 0.0)
    assert (snap["checks_total"], snap["degraded_total"]) == (5, 4)


def test_a_warning_is_logged_once_per_window_above_the_threshold(caplog, monkeypatch):
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "fail_mode", "open")
    clock = _Clock()
    meter = CheckDegradationMeter(window_seconds=60, warn_ratio=0.1, min_checks=10, clock=clock)
    with caplog.at_level(logging.WARNING, logger="agentfox.runtime.availability"):
        for i in range(9):
            meter.observe({"m": "timeout"} if i % 2 else {})
        assert not caplog.records  # under min_checks: no rate yet
        for _ in range(20):
            meter.observe({"m": "timeout"})
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "fail_mode=open" in message and "fail_mode=closed blocks them" in message
        clock.now += 61
        for _ in range(10):
            meter.observe({"m": "timeout"})
    assert len(caplog.records) == 2


def test_no_warning_below_the_threshold(caplog):
    meter = CheckDegradationMeter(warn_ratio=0.5, min_checks=1)
    with caplog.at_level(logging.WARNING, logger="agentfox.runtime.availability"):
        for i in range(40):
            meter.observe({"m": "timeout"} if i % 4 == 3 else {})
    assert not caplog.records
    assert meter.snapshot()["above_threshold"] is False


def test_health_is_unhealthy_while_the_share_is_above_threshold(monkeypatch):
    from agentfox.core.config import get_settings
    from agentfox.runtime.availability import reset_degradation_ledger, service_health

    reset_degradation_ledger()
    monkeypatch.setattr(get_settings(), "degraded_warn_min_checks", 5)
    reset_check_meter()
    try:
        for _ in range(5):
            get_check_meter().observe({})
        assert service_health(probe=False)["healthy"] is True
        for _ in range(5):
            get_check_meter().observe({"injection.classifier": "timeout"})
        health = service_health(probe=False)
        assert health["healthy"] is False
        assert health["checks"]["above_threshold"] is True
        assert health["checks"]["window_degraded"] == 5
    finally:
        reset_check_meter()


# --- end to end: counted, exposed, and never a silent pass ------------------------


class _TimesOut(BaseDetector):
    key = "injection.classifier"
    version = "1"
    surfaces = ("input",)
    timeout_ms = 20

    def available(self):
        return True

    def _detect(self, content, context):
        time.sleep(0.2)
        return []


PACK = """
key: load-pack
mode: enforce
rules:
  - id: pii.input
    when: {surface: [input], detection: {entity_prefix: PII}}
    effect: block
"""


@pytest.mark.parametrize("fail_mode", ["open", "closed"])
def test_a_degraded_check_is_counted_on_metrics_and_follows_fail_mode(
    session, monkeypatch, fail_mode
):
    from agentfox.core.config import get_settings
    from agentfox.exporters.prometheus import render_metrics
    from agentfox.platform.policy import PolicyDocument, save_policy
    from agentfox.platform.registry.service import register_agent
    from agentfox.runtime.enforcement import Enforcer

    reset_check_meter()
    try:
        monkeypatch.setattr(get_settings(), "fail_mode", fail_mode)
        agent = register_agent(session, "load-bot")
        save_policy(session, PolicyDocument.from_yaml(PACK), bind_mode="enforce")
        result = Enforcer(session, pipeline=DetectorPipeline([_TimesOut()])).evaluate(
            agent=agent, identity=None, content="hello", surface="input", persist=False
        )
        assert result.degraded == ["injection.classifier"]
        # Not a silent pass: closed blocks it, open allows it and says so.
        assert result.verdict == ("block" if fail_mode == "closed" else "allow")
        assert result.to_json()["degraded"] == ["injection.classifier"]
        metrics = render_metrics(session)
        assert "agentfox_checks_total 1" in metrics
        assert (
            'agentfox_checks_degraded_total{cause="timeout",detector="injection.classifier"} 1'
            in metrics
        )
        assert "agentfox_checks_degraded_ratio 1" in metrics
    finally:
        reset_check_meter()


def test_a_full_backstop_backlog_is_dropped_and_counted(monkeypatch):
    from agentfox.runtime.enforcement import enforcer

    reset_check_meter()
    try:
        monkeypatch.setattr(enforcer, "BACKSTOP_MAX_PENDING", 0)
        ran: list[bool] = []
        assert enforcer._submit_backstop(lambda: ran.append(True)) is False
        assert get_check_meter().snapshot()["backstop_shed_total"] == 1
        assert ran == []
    finally:
        reset_check_meter()
