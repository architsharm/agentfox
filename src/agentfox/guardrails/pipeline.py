"""Budgeted detector pipeline (P3-6, P3-7, P3-11 / NOM-RTG-06).

Latency is a product constraint here, not an implementation detail (principle X-7).
A governance tool that adds 400ms to every model call becomes a performance
incident, and performance incidents get the tool removed (Appendix E.2.1).

So the pipeline:

* runs detectors **concurrently**, cheapest-first;
* enforces a **per-detector timeout** and a **total budget** (NFR-1);
* on breach, degrades that detector to observe-only and records a
  ``budget_breach`` finding rather than silently skipping it — a control that
  quietly stops running while reporting ``effective`` is the failure mode that
  makes compliance products worthless (Appendix E.2.3);
* honours per-policy **fail-open / fail-closed** (P3-7), with the choice itself
  recorded as a governed setting.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field

from ..config import get_settings
from .base import Detection, DetectionContext, Detector, DetectorResult, available_detectors

log = logging.getLogger(__name__)

#: A thread pool is a long-lived, reusable resource — not a per-request
#: throwaway. `Enforcer.__init__` builds a fresh `DetectorPipeline()` whenever no
#: pipeline is explicitly injected (the overwhelming majority of call sites,
#: across every request the gateway serves), and nothing calls `shutdown()` on
#: the one it replaces, because `Enforcer` has no lifecycle hook to do so from.
#: Left as-is, every governed call leaks two `ThreadPoolExecutor`s worth of OS
#: threads for the rest of the process's life — found via a real, reproducible
#: test-suite failure: after enough Enforcer instantiations accumulate stragglers
#: (the pool exhaustion this module's own docstring already describes, just
#: across pools instead of within one), an ordinary detector call blew a 350ms
#: budget by nearly 2x and every detector on that call was skipped. Sharing
#: pools by `max_workers` keeps a caller that actually wants isolation (a
#: non-default worker count) unaffected, while the default case — everyone else —
#: stops leaking.
_shared_pool_lock = threading.Lock()
_shared_pools: dict[int, tuple[ThreadPoolExecutor, ThreadPoolExecutor]] = {}


def _get_shared_pools(max_workers: int) -> tuple[ThreadPoolExecutor, ThreadPoolExecutor]:
    with _shared_pool_lock:
        pools = _shared_pools.get(max_workers)
        if pools is None:
            pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="nom-detect")
            heavy_pool = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="nom-detect-heavy"
            )
            pools = (pool, heavy_pool)
            _shared_pools[max_workers] = pools
        return pools


#: Rough relative cost, used to start cheap detectors first so that a budget
#: breach loses the expensive-but-marginal signal rather than the cheap-and-decisive
#: one. Unlisted detectors sort last.
_COST_ORDER = {
    "secrets.native": 0,
    "injection.heuristic": 1,
    # a network round trip; run it after every local detector
    "injection.judgment": 95,
    "pii.judgment": 96,
    "pii.native": 2,
    "safety.lexicon": 3,
    "schema.json": 4,
    "pii.presidio": 10,
    "rails.guardrails_ai": 15,
    "safety.granite": 20,
    "safety.restricted": 20,
    "rails.nemo": 25,
}


@dataclass
class PipelineResult:
    results: list[DetectorResult] = field(default_factory=list)
    duration_ms: float = 0.0
    budget_ms: float = 0.0
    degraded: list[str] = field(default_factory=list)
    errored: list[str] = field(default_factory=list)

    @property
    def detections(self) -> list[Detection]:
        out: list[Detection] = []
        for r in self.results:
            out.extend(r.detections)
        return out

    @property
    def max_score(self) -> float:
        return max((r.score for r in self.results), default=0.0)

    @property
    def over_budget(self) -> bool:
        return self.duration_ms > self.budget_ms

    def by_entity(self) -> dict[str, list[Detection]]:
        grouped: dict[str, list[Detection]] = {}
        for det in self.detections:
            grouped.setdefault(det.entity_type, []).append(det)
        return grouped

    def summary(self) -> dict:
        return {
            "duration_ms": round(self.duration_ms, 2),
            "budget_ms": self.budget_ms,
            "over_budget": self.over_budget,
            "detectors_run": [r.detector_key for r in self.results],
            "degraded": self.degraded,
            "errored": self.errored,
            "entities": sorted(self.by_entity()),
            "max_score": round(self.max_score, 3),
        }


class DetectorPipeline:
    def __init__(
        self,
        detectors: list[Detector] | None = None,
        budget_ms: int | None = None,
        detector_timeout_ms: int | None = None,
        max_workers: int = 8,
    ) -> None:
        settings = get_settings()
        self.budget_ms = budget_ms if budget_ms is not None else settings.enforcement_budget_ms
        self.detector_timeout_ms = (
            detector_timeout_ms if detector_timeout_ms is not None else settings.detector_timeout_ms
        )
        self._explicit = detectors
        # A timed-out future's worker thread keeps running — Python cannot pre-empt
        # it (see the FutureTimeout handler below) — so a detector whose calls
        # occasionally exceed its own timeout leaves behind a straggler that
        # permanently occupies a pool slot until it eventually finishes. Under
        # sustained load that accumulates: enough stragglers exhaust the pool, and
        # then even the fast, always-on detectors (heuristic/pii/secrets/safety)
        # can't get a worker and start timing out too — a slow *opt-in* classifier
        # should never be able to take down the always-on safety net. Detectors
        # that declare their own `timeout_ms` (real per-call cost — currently the
        # model-backed ones) get a separate pool so their stragglers can only ever
        # starve each other, never the cheap detectors this one shares nothing with.
        # Both pools are shared across every DetectorPipeline with the same
        # max_workers (see _get_shared_pools) rather than created fresh per
        # instance — see that function's docstring for why.
        self._pool, self._heavy_pool = _get_shared_pools(max_workers)

    # -- selection -------------------------------------------------------
    def select(self, surface: str) -> list[Detector]:
        if self._explicit is not None:
            candidates = list(self._explicit)
        else:
            enabled = set(get_settings().enabled_detectors)
            candidates = [d for k, d in available_detectors().items() if k in enabled]
        applicable = [d for d in candidates if surface in d.surfaces and d.available()]
        return sorted(applicable, key=lambda d: _COST_ORDER.get(d.key, 50))

    # -- execution -------------------------------------------------------
    def run(
        self, content: str, context: DetectionContext, budget_ms: float | None = None
    ) -> PipelineResult:
        """P3-13: ``budget_ms`` lets a caller hand down what is left of a *request*-level
        allowance, which is smaller than the per-call budget once several surfaces have
        already been evaluated. Without it, a stack that respects 100 ms per call can
        still spend half a second on one request."""
        effective_budget = self.budget_ms if budget_ms is None else float(budget_ms)
        detectors = self.select(context.surface)
        # A detector that cannot physically finish inside the default budget —
        # currently only the judgment tiers, which make a network round trip
        # measured at a 332ms median — declares `requires_budget_ms`. Without
        # this the 300ms pre-flight budget (NFR-1) silently times it out on
        # every call, so enabling a hosted tier would buy nothing while looking
        # like it worked. Raising the budget is the honest alternative: an
        # operator who enables a hosted tier is choosing latency for recall,
        # and `PipelineResult.budget_ms` reports what was actually granted.
        # Detectors nobody opted into cannot trigger this, so NFR-1 still holds
        # for the default install.
        required = max((getattr(d, "requires_budget_ms", 0) or 0 for d in detectors), default=0)
        if required and required > effective_budget:
            effective_budget = float(required)
        result = PipelineResult(budget_ms=effective_budget)
        if not detectors:
            return result

        started = time.perf_counter()
        futures = {
            self._pool_for(d).submit(self._run_one, d, content, context): d for d in detectors
        }

        for future, detector in futures.items():
            elapsed_ms = (time.perf_counter() - started) * 1000
            remaining_ms = effective_budget - elapsed_ms
            # Never give a single detector more than its own timeout — the
            # detector's own declared ceiling if it has one, else the pipeline
            # default — and never more than what is left of the whole-pipeline
            # budget.
            own_timeout_ms = getattr(detector, "timeout_ms", None) or self.detector_timeout_ms
            allowance = min(own_timeout_ms, max(remaining_ms, 0.0))

            if allowance <= 0:
                result.results.append(
                    DetectorResult(
                        detector_key=detector.key,
                        version=detector.version,
                        status="skipped_budget",
                    )
                )
                result.degraded.append(detector.key)
                future.cancel()
                continue

            try:
                result.results.append(future.result(timeout=allowance / 1000))
            except FutureTimeout:
                # The worker thread keeps running (Python cannot pre-empt it); we
                # stop *waiting*, which is what protects the caller's latency. The
                # detector is recorded as degraded so control status reflects it.
                result.results.append(
                    DetectorResult(
                        detector_key=detector.key,
                        version=detector.version,
                        status="timeout",
                        duration_ms=allowance,
                    )
                )
                result.degraded.append(detector.key)
            except Exception as exc:  # a detector must never take the request down
                log.warning("detector %s failed: %s", detector.key, exc)
                result.results.append(
                    DetectorResult(
                        detector_key=detector.key,
                        version=detector.version,
                        status="error",
                        raw={"error": str(exc)[:500]},
                    )
                )
                result.errored.append(detector.key)

        result.duration_ms = (time.perf_counter() - started) * 1000
        return result

    def _pool_for(self, detector: Detector) -> ThreadPoolExecutor:
        return self._heavy_pool if getattr(detector, "timeout_ms", None) else self._pool

    @staticmethod
    def _run_one(detector: Detector, content: str, context: DetectionContext) -> DetectorResult:
        started = time.perf_counter()
        out = detector.detect(content, context)
        out.duration_ms = (time.perf_counter() - started) * 1000
        return out

    def shutdown(self) -> None:
        """No-op: the pools are shared across every DetectorPipeline with the same
        max_workers (see _get_shared_pools), so one instance tearing them down
        would break every other instance still using them. Kept as a method
        (rather than removed) for callers that already call it expecting a clean
        no-op rather than an AttributeError; nothing in this codebase currently
        calls it (confirmed by grep), and process-level cleanup of these pools
        happens naturally at interpreter exit, the same as any other module-level
        resource."""


def fail_verdict(fail_mode: str | None = None) -> str:
    """What a degraded pipeline means for the request (P3-7).

    ``open`` keeps the customer's agent working and accepts reduced coverage;
    ``closed`` blocks. Neither is right in general — which is why it is a governed,
    audited setting rather than a hard-coded default.
    """
    mode = fail_mode or get_settings().fail_mode
    return "block" if mode == "closed" else "allow"
