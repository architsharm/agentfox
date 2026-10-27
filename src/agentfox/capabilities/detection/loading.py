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

import threading
from collections.abc import Callable
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


class BatchedScorer:
    """Forward passes for one loaded text-classification model, batched across
    requests.

    Each caller hands in its texts and waits. One worker drains whatever is queued,
    up to ``max_batch`` texts, and runs them in a single forward pass under the
    model's inference lock, then hands each caller its rows. Under concurrency this
    turns N sequential passes into a few batched ones (the latency study: 8 texts in
    67 ms batched against 225 ms one by one). Results for a text already scored are
    served from an LRU cache keyed by its hash: agents resend the same system
    prompts, tool descriptions and retrieved chunks.
    """

    def __init__(self, pipe: Any, *, max_batch: int = 16, cache_size: int = 4096) -> None:
        import collections
        import queue

        self.pipe = pipe
        self.max_batch = max_batch
        self.cache_size = cache_size
        self._cache: collections.OrderedDict[str, list] = collections.OrderedDict()
        self._cache_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._run, name="agentfox-batch", daemon=True)
        self._worker.start()

    @staticmethod
    def _key(text: str) -> str:
        import hashlib

        return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()

    def score(self, texts: list[str]) -> list[list[dict[str, Any]]]:
        """The label rows for each of ``texts``, in order."""
        from concurrent.futures import Future

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
            future: Future = Future()
            self._queue.put(([texts[i] for i in missing], future))
            rows = future.result()
            with self._cache_lock:
                for i, row in zip(missing, rows, strict=True):
                    out[i] = row
                    if self.cache_size:
                        self._cache[self._key(texts[i])] = row
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        return [row or [] for row in out]

    def _run(self) -> None:
        import queue

        while True:
            jobs = [self._queue.get()]
            count = len(jobs[0][0])
            while count < self.max_batch:
                try:
                    job = self._queue.get_nowait()
                except queue.Empty:
                    break
                jobs.append(job)
                count += len(job[0])
            batch = [text for texts, _future in jobs for text in texts]
            try:
                with inference_lock(self.pipe):
                    # A Hugging Face pipeline given a list still runs it one text at a
                    # time unless told a batch size: this is the single padded pass.
                    scored = self.pipe(batch, batch_size=len(batch))
                rows = [r if isinstance(r, list) else [r] for r in scored]
                start = 0
                for texts, future in jobs:
                    future.set_result(rows[start : start + len(texts)])
                    start += len(texts)
            except Exception as exc:  # the callers see the failure, not the worker
                for _texts, future in jobs:
                    if not future.done():
                        future.set_exception(exc)


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
