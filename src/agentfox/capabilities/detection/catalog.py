"""What each detector catches, and where it comes from — for the Checks screen.

The detector registry knows how to run a check; it does not say what kind of problem
the check is for, or whether it is code that ships with AgentFox, an open-source
model someone has to download, an LLM judge that needs a provider, or something
the workspace brought itself. A customer choosing what runs asks exactly those
questions, so they are answered once, here, rather than guessed from a key in
TypeScript.

Licences are named only for the model ids this project ships as defaults and has
checked. A model an operator configured instead is reported with no licence rather
than an invented one.
"""

from __future__ import annotations

from typing import Any

from agentfox.capabilities.detection.models import models_for

#: Display order of the groups, and their names.
GROUPS: tuple[tuple[str, str], ...] = (
    ("attacks", "Prompt attacks"),
    ("data", "Personal data & secrets"),
    ("content", "Harmful content"),
    ("grounding", "Grounding & wrong answers"),
    ("yours", "Your own"),
)

#: Detector key prefix -> group, most specific first.
_GROUP_BY_KEY: tuple[tuple[str, str], ...] = (
    ("custom.", "yours"),
    ("injection.", "attacks"),
    ("code.", "attacks"),
    ("rails.nemo", "attacks"),
    ("pii.", "data"),
    ("secrets.", "data"),
    ("safety.", "content"),
    ("grounding.", "grounding"),
    ("schema.", "grounding"),
    ("rails.guardrails_ai", "grounding"),
)

#: Entity prefix -> group, for detectors that report one (the Hub validators).
_GROUP_BY_ENTITY = {
    "INJECTION": "attacks",
    "DISCLOSURE": "attacks",
    "CODE": "attacks",
    "ACTION": "attacks",
    "PII": "data",
    "SECRET": "data",
    "SAFETY": "content",
    "BRAND": "content",
    "TOPIC": "content",
    "SCHEMA": "grounding",
    "GROUNDING": "grounding",
}

#: The default model ids this project ships, and their licences.
MODEL_LICENSES = {
    "leolee99/PIGuard": "MIT",
    "protectai/deberta-v3-base-prompt-injection-v2": "Apache-2.0",
    "sentence-transformers/all-MiniLM-L6-v2": "Apache-2.0",
    "cross-encoder/nli-deberta-v3-small": "Apache-2.0",
    "ibm-granite/granite-guardian-3.0-2b": "Apache-2.0",
    "meta-llama/Llama-Guard-3-8B": "Llama 3.1 Community (restricted)",
}

#: Licences of the open-source packages wrapped without a model download.
_PACKAGE_LICENSES = {
    "pii.presidio": "MIT",
    "rails.nemo": "Apache-2.0",
    "rails.guardrails_ai": "Apache-2.0",
}

#: Detectors decided by a judgment tier (JEV or an LLM), not by code on this host.
JUDGE_DETECTORS = frozenset({"injection.judgment", "pii.judgment"})

#: Where a detector runs, in the three words a customer uses.
_WHERE = {
    "input": "input",
    "output": "output",
    "tool_args": "tools",
    "tool_result": "tools",
    "tool_call": "tools",
    "mcp": "tools",
    "retrieved": "context",
    "memory_write": "context",
    "agent_message": "context",
}


def group_of(detector: Any) -> str:
    key = str(getattr(detector, "key", ""))
    spec = getattr(detector, "spec", None)
    entity = str(getattr(spec, "entity_type", "") or "")
    if entity:
        return _GROUP_BY_ENTITY.get(entity.split(".")[0], "content")
    for prefix, group in _GROUP_BY_KEY:
        if key.startswith(prefix):
            return group
    return "content"


def source_of(detector: Any) -> str:
    """builtin | open_source | llm_judge | yours."""
    key = str(getattr(detector, "key", ""))
    if key.startswith("custom."):
        return "yours"
    if key in JUDGE_DETECTORS:
        return "llm_judge"
    if models_for(detector) or key in _PACKAGE_LICENSES or key.startswith("rails."):
        return "open_source"
    return "builtin"


def where(surfaces: tuple[str, ...] | list[str]) -> list[str]:
    """input / output / tools / context, in that order, for the surfaces given."""
    found = {_WHERE.get(s, "context") for s in surfaces}
    return [w for w in ("input", "output", "tools", "context") if w in found]


def describe(detector: Any) -> dict[str, Any]:
    """The Checks-screen facts for one detector."""
    key = str(getattr(detector, "key", ""))
    models = [{"id": m, "license": MODEL_LICENSES.get(m)} for m in models_for(detector)]
    license_ = (
        models[0]["license"]
        if models
        else _PACKAGE_LICENSES.get(key)
        or ("Per validator" if key.startswith("rails.hub.") else None)
    )
    return {
        "group": group_of(detector),
        "source": source_of(detector),
        "where": where(tuple(getattr(detector, "surfaces", ()) or ())),
        "models": models,
        "license": license_,
    }
