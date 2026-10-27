"""Load a detector's model once, under a lock, however many requests arrive first.

Detectors run on the pipeline's thread pool, so the first burst of requests to a cold
detector reaches its loader from several threads at once. `functools.cached_property`
does not lock (it stopped in Python 3.12), and neither half of what a loader does is
safe to race: `transformers` imports its submodules lazily, so concurrent first imports
fail with ``ImportError: cannot import name 'pipeline'``, and building the same model
in several threads while others run inference on it crashed the process with a
segmentation fault. One lock for every loader, because the import race is process-wide.
"""

from __future__ import annotations

import collections
import contextlib
import contextvars
import threading
from collections.abc import Callable, Iterator
from typing import Any, Generic, TypeVar

T = TypeVar("T")

_load_lock = threading.RLock()


class load_once(Generic[T]):  # noqa: N801 - used as a decorator, like cached_property
    """`cached_property` that builds its value at most once, even under concurrency.

    The common path, once loaded, reads the instance dict and takes no lock.
    """

    def __init__(self, func: Callable[[Any], T]) -> None:
        self.func = func
        self.attrname = func.__name__
        self.__doc__ = func.__doc__

    def __set_name__(self, owner: type, name: str) -> None:
        self.attrname = name

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self
        cache = instance.__dict__
        if self.attrname in cache:
            return cache[self.attrname]
        with _load_lock:
            if self.attrname not in cache:
                cache[self.attrname] = self.func(instance)
            return cache[self.attrname]


def inference_lock(model: Any) -> threading.Lock:
    """The lock that serialises forward passes on one loaded model.

    Loading once was not enough: concurrent forward passes on the same DeBERTa model
    from the pipeline's threads still segfaulted (torch 2.13, macOS arm64), inside
    plain tensor ops. One pass at a time per model is what makes it safe; a request
    that waits past its budget is reported as degraded like any other timeout.
    """
    lock = getattr(model, "_agentfox_inference_lock", None)
    if lock is None:
        with _load_lock:
            lock = getattr(model, "_agentfox_inference_lock", None)
            if lock is None:
                lock = threading.Lock()
                model._agentfox_inference_lock = lock
    return lock


class CallScope:
    """The bounds of one pooled detector call, set by the pipeline that waits for it.

    ``deadline`` (a `time.perf_counter()` value) is the latest moment the pipeline
    could still want the answer; `abandon()` is called when it stops waiting (the
    detector timed out or was shed for budget). Work queued for a call nobody waits
    for any more is dropped before it reaches the model instead of being run anyway:
    under load that leftover work was what pushed the next requests past their own
    allowance.
    """

    def __init__(self, deadline: float | None = None) -> None:
        self.deadline = deadline
        self._lock = threading.Lock()
        self._abandoned = False
        self._callbacks: list[Callable[[], Any]] = []

    @property
    def abandoned(self) -> bool:
        return self._abandoned

    def remaining_s(self) -> float | None:
        """Seconds left before the deadline (never negative), or None for no deadline."""
        if self.deadline is None:
            return None
        import time

        return max(self.deadline - time.perf_counter(), 0.0)

    def abandon(self) -> None:
        with self._lock:
            if self._abandoned:
                return
            self._abandoned = True
            callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            try:
                callback()
            except Exception:  # noqa: BLE001 - abandoning must never raise into the pipeline
                pass

    def on_abandon(self, callback: Callable[[], Any]) -> None:
        with self._lock:
            if not self._abandoned:
                self._callbacks.append(callback)
                return
        callback()


_call_scope: contextvars.ContextVar[CallScope | None] = contextvars.ContextVar(
    "agentfox_call_scope", default=None
)
_background: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agentfox_background_inference", default=False
)


def current_scope() -> CallScope | None:
    """The bounds of the detector call running in this context, if the pipeline set any."""
    return _call_scope.get()


def enter_scope(scope: CallScope | None) -> None:
    """Bind ``scope`` to the current context (the pipeline runs this inside the copied
    context it hands each pooled detector)."""
    _call_scope.set(scope)


@contextlib.contextmanager
def background_inference() -> Iterator[None]:
    """Forward passes started inside this block yield to every pass a request is
    waiting on: they run only when no request-path work is queued. For advisory work
    done after the response (the classifier's backstop)."""
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


class InferenceAbandoned(TimeoutError):
    """The caller stopped waiting before its texts reached the model; they were not
    scored. Raised only after the pipeline has already recorded the detector as
    degraded, so nothing reads it as "no detection"."""


class InferenceShed(RuntimeError):
    """Background work refused because its backlog is full (counted, never silent)."""


class _Job:
    __slots__ = ("scorer", "texts", "future", "background", "enqueued")

    def __init__(self, scorer: BatchedScorer, texts: list[str], background: bool) -> None:
        import time
        from concurrent.futures import Future

        self.scorer = scorer
        self.texts = texts
        self.future: Future = Future()
        self.background = background
        self.enqueued = time.perf_counter()


class InferenceScheduler:
    """One worker that runs every batched forward pass in the process, request-path
    work first.

    Measured under 16 concurrent clients (one gateway process, MPS): with a worker per
    model, the advisory backstop model's passes, which run after the response, took
    turns on the same device with the request-path classifier's, and each request-path
    pass took 3-8x its solo time; with the per-call wait counted against a 250 ms
    allowance, most checks were answered without the classifier. Here passes never
    overlap, request-path jobs (FIFO across models) always go before background ones,
    a pass batches every queued job for the same model up to ``max_batch`` texts, and
    a job whose caller has given up is dropped before it reaches the model.
    """

    def __init__(self, *, max_background: int = 256) -> None:
        self.max_background = max_background
        self._cv = threading.Condition()
        self._urgent: collections.deque[_Job] = collections.deque()
        self._background: collections.deque[_Job] = collections.deque()
        self._worker: threading.Thread | None = None
        self.stats: dict[str, float] = {
            "passes": 0,
            "texts": 0,
            "abandoned": 0,
            "shed": 0,
            "queue_wait_ms_max": 0.0,
        }

    def submit(self, job: _Job) -> None:
        with self._cv:
            if job.background:
                if len(self._background) >= self.max_background:
                    self.stats["shed"] += 1
                    raise InferenceShed(
                        f"background inference backlog full ({self.max_background} jobs)"
                    )
                self._background.append(job)
            else:
                self._urgent.append(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run, name="agentfox-inference", daemon=True
                )
                self._worker.start()
            self._cv.notify()

    def pending(self) -> dict[str, int]:
        with self._cv:
            return {"request_path": len(self._urgent), "background": len(self._background)}

    def _next_batch(self) -> list[_Job]:
        """Under the condition: the next pass's jobs, all for one model, already
        marked running (so a late `cancel()` cannot drop a job mid-pass)."""
        import time

        while True:
            while not self._urgent and not self._background:
                self._cv.wait()
            queue = self._urgent if self._urgent else self._background
            # Drop jobs whose caller already gave up, from the head.
            while queue and not queue[0].future.set_running_or_notify_cancel():
                queue.popleft()
                self.stats["abandoned"] += 1
            if not queue:
                continue
            head = queue.popleft()
            jobs, count, keep = [head], len(head.texts), collections.deque()
            limit = head.scorer.max_batch
            while queue:
                job = queue.popleft()
                if job.scorer is not head.scorer or count + len(job.texts) > limit:
                    keep.append(job)
                    continue
                if not job.future.set_running_or_notify_cancel():
                    self.stats["abandoned"] += 1
                    continue
                jobs.append(job)
                count += len(job.texts)
            queue.extendleft(reversed(keep))
            now = time.perf_counter()
            wait_ms = max((now - j.enqueued) * 1000 for j in jobs)
            self.stats["queue_wait_ms_max"] = max(self.stats["queue_wait_ms_max"], wait_ms)
            return jobs

    def _run(self) -> None:
        while True:
            with self._cv:
                jobs = self._next_batch()
            scorer = jobs[0].scorer
            batch = [text for job in jobs for text in job.texts]
            try:
                rows = scorer._forward(batch)
                start = 0
                for job in jobs:
                    job.future.set_result(rows[start : start + len(job.texts)])
                    start += len(job.texts)
                self.stats["passes"] += 1
                self.stats["texts"] += len(batch)
            except Exception as exc:  # the callers see the failure, not the worker
                for job in jobs:
                    if not job.future.done():
                        job.future.set_exception(exc)


_scheduler: InferenceScheduler | None = None


def scheduler() -> InferenceScheduler:
    """The process's one `InferenceScheduler`."""
    global _scheduler
    if _scheduler is None:
        with _load_lock:
            if _scheduler is None:
                _scheduler = InferenceScheduler()
    return _scheduler


class BatchedScorer:
    """Forward passes for one loaded text-classification model, batched across
    requests.

    Each caller hands in its texts and waits. The process's `InferenceScheduler`
    batches whatever is queued for this model, up to ``max_batch`` texts, into one
    forward pass under the model's inference lock, then hands each caller its rows.
    Under concurrency this turns N sequential passes into a few batched ones (the
    latency study: 8 texts in 67 ms batched against 225 ms one by one). A caller
    inside a pipeline call waits only until that call's deadline, and its texts are
    dropped unscored if the pipeline stops waiting first. Results for a text already
    scored are served from an LRU cache keyed by its hash: agents resend the same
    system prompts, tool descriptions and retrieved chunks.
    """

    def __init__(
        self,
        pipe: Any,
        *,
        max_batch: int = 16,
        cache_size: int = 4096,
        scheduler: InferenceScheduler | None = None,
    ) -> None:
        self.pipe = pipe
        self.max_batch = max_batch
        self.cache_size = cache_size
        self._cache: collections.OrderedDict[str, list] = collections.OrderedDict()
        self._cache_lock = threading.Lock()
        self._scheduler = scheduler

    @staticmethod
    def _key(text: str) -> str:
        import hashlib

        return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()

    def score(self, texts: list[str]) -> list[list[dict[str, Any]]]:
        """The label rows for each of ``texts``, in order."""
        from concurrent.futures import CancelledError

        out: list[list[dict[str, Any]] | None] = [None] * len(texts)
        missing: list[int] = []
        with self._cache_lock:
            for i, text in enumerate(texts):
                hit = self._cache.get(self._key(text))
                if hit is not None:
                    self._cache.move_to_end(self._key(text))
                    out[i] = hit
                else:
                    missing.append(i)
        if missing:
            scope = current_scope()
            if scope is not None and scope.abandoned:
                raise InferenceAbandoned("the pipeline stopped waiting before inference")
            job = _Job(self, [texts[i] for i in missing], background=_background.get())
            (self._scheduler or scheduler()).submit(job)
            if scope is not None:
                scope.on_abandon(job.future.cancel)
            try:
                rows = job.future.result(timeout=scope.remaining_s() if scope else None)
            except (CancelledError, TimeoutError) as exc:
                # Not started: it never will be. Started: it finishes and is ignored.
                job.future.cancel()
                raise InferenceAbandoned(
                    "the pipeline stopped waiting before this text was scored"
                ) from exc
            with self._cache_lock:
                for i, row in zip(missing, rows, strict=True):
                    out[i] = row
                    if self.cache_size:
                        self._cache[self._key(texts[i])] = row
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        return [row or [] for row in out]

    def _forward(self, batch: list[str]) -> list[list[dict[str, Any]]]:
        """One padded forward pass over ``batch`` (run by the scheduler's worker)."""
        with inference_lock(self.pipe):
            # A Hugging Face pipeline given a list still runs it one text at a time
            # unless told a batch size: this is the single padded pass.
            scored = self.pipe(batch, batch_size=len(batch))
        return [r if isinstance(r, list) else [r] for r in scored]


def batched(pipe: Any) -> BatchedScorer:
    """The one `BatchedScorer` for a loaded model."""
    scorer = getattr(pipe, "_agentfox_batched", None)
    if scorer is None:
        with _load_lock:
            scorer = getattr(pipe, "_agentfox_batched", None)
            if scorer is None:
                from agentfox.core.config import get_settings

                size = int(getattr(get_settings(), "classifier_cache_size", 4096))
                scorer = BatchedScorer(pipe, cache_size=size)
                pipe._agentfox_batched = scorer
    return scorer


def model_device() -> str:
    """Where this process runs its models: "cpu", "cuda" or "mps".

    `model_device = "auto"` picks the fastest one present. Only a model server with a
    GPU usually has a choice; everything else runs on CPU as it always has.
    """
    from agentfox.core.config import get_settings

    wanted = (get_settings().model_device or "auto").lower()
    if wanted != "auto":
        return wanted
    try:
        import torch
    except Exception:  # noqa: BLE001 - no torch means no model runs here anyway
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def to_model_device(tensors: Any, model: Any) -> Any:
    """Move inputs to the device a model's weights are on. A no-op for a stand-in
    model with no device, which is what the unit tests pass."""
    device = getattr(model, "device", None)
    return tensors.to(device) if device is not None else tensors
