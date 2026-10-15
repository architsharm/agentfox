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
