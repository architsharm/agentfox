"""The model weights a detector needs, and fetching them on purpose.

Model-backed detectors load weights from the local cache only — never at request time,
so a request never waits on a download and nothing leaves the machine while traffic is
flowing. That made "not installed" a dead end: nothing said how to get the model. This
names it, per detector, and `agentfox admin detectors pull <key>` downloads it once,
when an operator asks.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

from agentfox.core.config import get_settings

#: Set by the platforms where a request handler runs on a read-only file system and
#: is frozen once it has answered: Vercel, AWS Lambda, Google Cloud Functions.
_SERVERLESS_ENV = ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME", "FUNCTION_TARGET")


def models_for(detector: Any) -> list[str]:
    """The model ids a detector loads, or [] for a detector with no model."""
    ids = [getattr(detector, "model_id", None), getattr(detector, "secondary_model_id", None)]
    if getattr(detector, "key", "") == "custom.topics":
        ids.append(get_settings().embedding_similarity_model)
    return [i for i in dict.fromkeys(ids) if isinstance(i, str) and i]


def pull_hint(detector: Any) -> str | None:
    """What to run so this detector can work here, when its model is what is missing."""
    if not models_for(detector):
        return None
    return f"agentfox admin detectors pull {detector.key}"


def serverless() -> bool:
    """True where this process cannot keep a downloaded model: a serverless function
    whose file system is read-only and whose next request may be a fresh instance."""
    return any(os.environ.get(name) for name in _SERVERLESS_ENV)


def pull_blocker(detector: Any) -> str | None:
    """Why this server cannot download the detector's model itself, or None if it can.

    The answer always ends in what to do instead, because the person reading it is
    looking at a button that did not work.
    """
    where = f"Run `agentfox admin detectors pull {detector.key}` where your gateway runs."
    if serverless():
        return (
            "This gateway runs serverless, on a read-only file system, so it cannot "
            f"keep a downloaded model. {where}"
        )
    if importlib.util.find_spec("huggingface_hub") is None:
        return (
            "The model libraries are not installed on this gateway. Install them with "
            f"`pip install 'agentfox[classifiers]'`, restart, then download again. Or: {where}"
        )
    return None


def pull(detector: Any) -> list[str]:  # pragma: no cover - downloads
    """Download every model this detector loads into the local cache. Returns the ids."""
    from huggingface_hub import snapshot_download

    ids = models_for(detector)
    for model_id in ids:
        snapshot_download(model_id)
    return ids
