"""Budgeted detector pipeline (NOM-RTG-06).

Latency is a product constraint here, not an implementation detail.
A governance tool that adds 400ms to every model call becomes a performance
incident, and performance incidents get the tool removed.

So the pipeline:

* runs detectors **concurrently**, cheapest-first;
* enforces a **per-detector timeout** and a **total budget**;
* on breach, degrades that detector to observe-only and records a
  ``budget_breach`` finding rather than silently skipping it — a control that
  quietly stops running while reporting ``effective`` is the failure mode that
  makes compliance products worthless;
* honours per-policy **fail-open / fail-closed**, with the choice itself
  recorded as a governed setting.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field

from agentfox.capabilities.detection.base import (
    Detection,
    DetectionContext,
    Detector,
    DetectorResult,
    all_detectors,
)
from agentfox.capabilities.detection.loading import CallScope, enter_scope
from agentfox.capabilities.judgment.jev import MALFORMED, OUTAGE
from agentfox.core.config import get_settings

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

#: The heavy pool's size, as a multiple of ``max_workers``. Its threads mostly wait:
#: a model-backed detector hands its texts to the process's inference scheduler and
#: blocks until its batch is scored. Sized like the light pool, it became the
#: concurrency limit instead of the model: at 16 concurrent checks, half of them
#: queued for a thread (measured p90 200 ms of a 250 ms allowance) before their text
#: even reached the batcher, and the batches it did form stayed small. A waiting
#: thread whose call is abandoned is released at once (`CallScope.abandon`), so the
#: larger pool does not accumulate stragglers.
HEAVY_POOL_FACTOR = 4


def _get_shared_pools(max_workers: int) -> tuple[ThreadPoolExecutor, ThreadPoolExecutor]:
    with _shared_pool_lock:
        pools = _shared_pools.get(max_workers)
        if pools is None:
            pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="nom-detect")
            heavy_pool = ThreadPoolExecutor(
                max_workers=max_workers * HEAVY_POOL_FACTOR, thread_name_prefix="nom-detect-heavy"
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
    "unicode.tags": 0,
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
    #: Detectors that did not check this content: timed out, shed for budget,
    #: errored (raised, or reported `status="error"`), or a judge that did not
    #: answer. This is what `fail_mode` reads.
    degraded: list[str] = field(default_factory=list)
    #: The subset of `degraded` that failed with an error rather than running out
    #: of time; the reason is on the detector's result (`raw["error"]`).
    errored: list[str] = field(default_factory=list)
    #: LLM judges that were asked and did not answer on this request: an outage
    #: (no tier reachable, an error), a timeout, or the budget running out before
    #: they started — detector key to the entity types that judge would have
    #: produced. Every one is also in `degraded` (an outage is reduced coverage,
    #: whichever way it showed up), so the deployment's and the packs' `fail_mode`
    #: see it exactly as they see a timeout; the entities are what lets the judgment
    #: posture's `fail_closed` block only where an enforcing rule depended on them.
    #:
    #: A judge that was *not asked* is not here: a payload the egress gate refused
    #: (`pii_egress=block` on text with an email address in it) or a tier with no
    #: key reports `status="unavailable"` with a cause other than `outage`, and is
    #: coverage the operator chose not to have, not an outage.
    judge_outage: dict[str, list[str]] = field(default_factory=dict)

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

    def degradation(self) -> dict[str, str]:
        """Each degraded detector and why: its status, and for an error the reason."""
        by_key = {r.detector_key: r for r in self.results}
        out: dict[str, str] = {}
        for key in dict.fromkeys(self.degraded):
            run = by_key.get(key)
            if run is None:
                out[key] = "degraded"
                continue
            why = run.status
            if run.status == "error":
                raw = run.raw or {}
                error = raw.get("error") or "; ".join(
                    f"{d.get('model')}: {d.get('error')}" for d in raw.get("degraded") or []
                )
                if error:
                    why = f"error: {str(error)[:200]}"
            elif run.status == "unavailable" and (run.raw or {}).get("cause"):
                why = f"unavailable ({run.raw['cause']})"
            out[key] = why
        return out

    def summary(self) -> dict:
        return {
            "duration_ms": round(self.duration_ms, 2),
            "budget_ms": self.budget_ms,
            "over_budget": self.over_budget,
            "detectors_run": [r.detector_key for r in self.results],
            "degraded": self.degraded,
            "errored": self.errored,
            "degradation": self.degradation(),
            "judge_outage": sorted(self.judge_outage),
            "entities": sorted(self.by_entity()),
            "max_score": round(self.max_score, 3),
        }


def _applies(detector: Detector, context: DetectionContext) -> bool:
    """Whether a detector has anything to do on this request.

    A detector whose work depends on the workspace's own rules (`custom.validators`)
    says so through `applies(context)`. Without this it was submitted on every
    request just to find no rules, and because it declares a timeout it queues in
    the heavy pool: behind a slow model's stragglers, that empty check waited out
    the request's budget (CI measured 100–101 ms against a 100 ms budget).
    """
    applies = getattr(detector, "applies", None)
    return bool(applies(context)) if callable(applies) else True


def _required_budget(detector: Detector, context: DetectionContext) -> int:
    """What a detector needs this request: its own `budget_for(context)` when its
    need depends on the request (a workspace rule that asks a model), else its
    fixed `requires_budget_ms`."""
    budget_for = getattr(detector, "budget_for", None)
    if callable(budget_for):
        return int(budget_for(context) or 0)
    return int(getattr(detector, "requires_budget_ms", 0) or 0)


def _own_timeout(detector: Detector, context: DetectionContext) -> int | None:
    """A detector's ceiling for this request: its `timeout_for(context)` when that
    depends on the request (a model reading long text), else its fixed `timeout_ms`."""
    timeout_for = getattr(detector, "timeout_for", None)
    if callable(timeout_for):
        return int(timeout_for(context) or 0) or None
    return getattr(detector, "timeout_ms", None)


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
    def select(
        self, surface: str, enabled: frozenset[str] | set[str] | None = None
    ) -> list[Detector]:
        """``enabled`` is a workspace's own choice (`detector_settings.enabled_for`);
        without it, the deployment's `enabled_detectors`."""
        if self._explicit is not None:
            candidates = list(self._explicit)
        else:
            chosen = set(enabled) if enabled is not None else set(get_settings().enabled_detectors)
            # Only the chosen detectors are asked whether they can run: asking all
            # of them on every request cost more than the detectors themselves.
            candidates = [d for k, d in all_detectors().items() if k in chosen]
        applicable = [d for d in candidates if surface in d.surfaces and d.available()]
        return sorted(applicable, key=lambda d: _COST_ORDER.get(d.key, 50))

    # -- execution -------------------------------------------------------
    def run(
        self, content: str, context: DetectionContext, budget_ms: float | None = None
    ) -> PipelineResult:
        """``budget_ms`` lets a caller hand down what is left of a *request*-level
        allowance, which is smaller than the per-call budget once several surfaces have
        already been evaluated. Without it, a stack that respects 100 ms per call can
        still spend half a second on one request."""
        effective_budget = self.budget_ms if budget_ms is None else float(budget_ms)
        deferred = (context.extra or {}).get("deferred_detectors") or ()
        detectors = [
            d
            for d in self.select(context.surface, context.enabled_detectors)
            if _applies(d, context) and d.key not in deferred
        ]
        # A detector that cannot physically finish inside the default budget —
        # currently only the judgment tiers, which make a network round trip
        # measured at a 332ms median — declares `requires_budget_ms`. Without
        # this the 300ms pre-flight budget silently times it out on
        # every call, so enabling a hosted tier would buy nothing while looking
        # like it worked. Raising the budget is the honest alternative: an
        # operator who enables a hosted tier is choosing latency for recall,
        # and `PipelineResult.budget_ms` reports what was actually granted.
        # Detectors nobody opted into cannot trigger this, so the default install
        # keeps the default budget.
        # How much text this check reads: a model's cost grows with it (see
        # `_TransformersClassifier.budget_for`).
        context.extra.setdefault("content_chars", len(content or ""))
        required = max((_required_budget(d, context) for d in detectors), default=0)
        if required and required > effective_budget:
            effective_budget = float(required)
        result = PipelineResult(budget_ms=effective_budget)
        if not detectors:
            return result

        started = time.perf_counter()
        # Each detector runs in a copy of this request's context: pool threads don't
        # inherit context variables, and the request's judgment posture (its judge
        # tiers, whether personal data may reach a judge) and tenant live in them.
        # One copy per submit, because a context can't be entered by two threads.
        # Built-in pattern detectors (no declared `timeout_ms`: secrets, injection
        # heuristic, PII, lexicon, schema, unicode, insecure code) take well under a
        # millisecond. They run here, in the request's own thread, and are never
        # skipped for time: a wall-clock deadline on them under CPU load let a check
        # pass with the secrets and injection patterns unread. Detectors that declare
        # a timeout (models, network judges, user-defined code) are submitted first,
        # so they run while these do, and stay under the budget.
        inline = [d for d in detectors if _runs_inline(d)]
        pooled = [d for d in detectors if not _runs_inline(d)]
        # Judges of one kind asking about this content share one model call
        # (`panel.ask_shared`); each needs to know how many of them run here.
        party: dict[str, int] = {}
        for d in pooled:
            if getattr(d, "shares_judge_call", False):
                party[d.kind.value] = party.get(d.kind.value, 0) + 1
        if party:
            context.extra["judge_party"] = party
        # Each pooled call carries its bounds: no wait below can outlast the whole
        # budget, and `abandon()` (on a timeout or a budget skip) drops whatever it
        # still has queued for a model, so work nobody waits for does not delay the
        # next request's detectors.
        deadline = started + effective_budget / 1000
        futures: dict = {}
        scopes: dict[str, CallScope] = {}
        for d in pooled:
            scope = scopes[d.key] = CallScope(deadline)
            ctx = contextvars.copy_context()
            ctx.run(enter_scope, scope)
            futures[self._pool_for(d).submit(ctx.run, self._run_one, d, content, context)] = d
        for detector in inline:
            try:
                finished = self._run_one(detector, content, context)
                result.results.append(finished)
                if finished.status == "error":
                    _errored(result, detector, context)
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
                _errored(result, detector, context)

        for future, detector in futures.items():
            elapsed_ms = (time.perf_counter() - started) * 1000
            remaining_ms = effective_budget - elapsed_ms
            # Never give a single detector more than its own timeout — the
            # detector's own declared ceiling if it has one, else the pipeline
            # default — and never more than what is left of the whole-pipeline
            # budget.
            own_timeout_ms = _own_timeout(detector, context) or self.detector_timeout_ms
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
                _judge_out(result, detector, context)
                future.cancel()
                scopes[detector.key].abandon()
                continue

            try:
                finished = future.result(timeout=allowance / 1000)
                result.results.append(finished)
                # A detector that caught its own failure (an unreachable endpoint)
                # reports it rather than raising; it is still a failure to count.
                if finished.status == "error":
                    _errored(result, detector, context)
                # A judge that was asked and got no answer: the same reduced
                # coverage as a judge that timed out, so it degrades the same way.
                elif finished.status == "unavailable" and finished.raw.get("cause") == OUTAGE:
                    _judge_out(result, detector, context, entities=finished.raw.get("entities"))
                # A judge that answered off-format: the service is up, so it is not an
                # outage (no `fail_closed` block), but nothing was checked. It degrades,
                # so `fail_mode` and control status see it: an input crafted to make the
                # judge reply unparseably must not switch the judge off unseen.
                elif finished.status == "unavailable" and finished.raw.get("cause") == MALFORMED:
                    if detector.key not in result.degraded:
                        result.degraded.append(detector.key)
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
                _judge_out(result, detector, context)
                # Still queued (not started): drop it. Left in the pool it runs anyway
                # after the request has moved on, delaying the next request's detectors.
                future.cancel()
                # Started and waiting on a model: drop its texts from the inference
                # queue and release the thread.
                scopes[detector.key].abandon()
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
                _errored(result, detector, context)

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


#: The built-in in-process pattern detectors: regex and character scans that take
#: well under a millisecond. Only these run inline and unbudgeted; any other detector
#: (a model, a judge, a workspace's own patterns, a plugin or pack) is pooled under
#: its deadline, because nothing guarantees it is fast.
INLINE_DETECTORS = frozenset(
    {
        "secrets.native",
        "injection.heuristic",
        "pii.native",
        "safety.lexicon",
        "schema.json",
        "unicode.tags",
        "code.insecure",
    }
)


def _runs_inline(detector: Detector) -> bool:
    from agentfox.capabilities.detection.base import get_detector

    # The registered built-in itself, not a stand-in that borrowed its key.
    return detector.key in INLINE_DETECTORS and get_detector(detector.key) is detector


def judge_entities(detector: Detector, context: DetectionContext) -> tuple[str, ...]:
    """The entity types this detector asks an LLM judge for on this request.

    Empty for a detector that asks no judge. One that does says so through
    `judge_entities(context)`: the two judgment detectors and a judge validator
    always, `custom.validators` for the workspace rules here that use a judge.
    """
    fn = getattr(detector, "judge_entities", None)
    return tuple(fn(context)) if callable(fn) else ()


def _is_judge(detector: Detector) -> bool:
    """A detector that *is* an LLM judge, so any failure of it is the judge's."""
    from agentfox.capabilities.detection.catalog import source_of

    return source_of(detector) == "llm_judge"


def _errored(result: PipelineResult, detector: Detector, context: DetectionContext) -> None:
    """Record a detector that failed (raised, or reported `status="error"`).

    An error is reduced coverage exactly as a timeout is: the detector did not
    check this content. So it is degraded too, and the deployment's and the packs'
    `fail_mode` decide it the way they decide a timeout (`closed` blocks as
    `pipeline.fail_closed`, `open` allows and records the gap). `errored` keeps
    saying *how* it degraded. A judge that errored is also a judge outage.
    """
    if detector.key not in result.errored:
        result.errored.append(detector.key)
    if detector.key not in result.degraded:
        result.degraded.append(detector.key)
    if _is_judge(detector):
        _judge_out(result, detector, context)


def _judge_out(
    result: PipelineResult,
    detector: Detector,
    context: DetectionContext,
    *,
    entities: list[str] | None = None,
) -> None:
    """Record a judge that did not answer — if this detector asks one here.

    Also degrades it, so a judge that said "unreachable" and one that timed out
    reach `fail_mode` the same way. A non-judge detector is left exactly as before.
    """
    found = list(entities) if entities else list(judge_entities(detector, context))
    if not found and not _is_judge(detector):
        return
    result.judge_outage[detector.key] = found
    if detector.key not in result.degraded:
        result.degraded.append(detector.key)


def fail_verdict(fail_mode: str | None = None) -> str:
    """What a degraded pipeline means for the request.

    ``open`` keeps the customer's agent working and accepts reduced coverage;
    ``closed`` blocks. Neither is right in general — which is why it is a governed,
    audited setting rather than a hard-coded default.
    """
    mode = fail_mode or get_settings().fail_mode
    return "block" if mode == "closed" else "allow"
