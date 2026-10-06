"""Response-shaping for enforcement verdicts: names that say which one took effect.

An :class:`~agentfox.runtime.enforcement.EnforcementResult` carries two verdicts and the
field names do not say which is which:

``verdict``
    What actually happened to this request. In observe mode it is ``allow``, because
    observe mode does not stop traffic.
``effective_verdict``
    The counterfactual: what the bound policy asserts *should* happen. In observe mode
    this is the verdict that did **not** take effect.

"effective" reads as the authoritative one, and it is the hypothetical. An integrator
who gates on it is, in observe mode, blocking traffic the platform allowed — a
rollout that is supposed to change nothing starts refusing requests.

So every gateway response adds two aliases next to the existing keys:

``applied_verdict``
    Identical to ``verdict``. What happened.
``would_be_verdict``
    Identical to ``effective_verdict``. What would happen under full enforcement.

The old keys stay, with the same values, so nothing that reads them breaks. This
renames nothing and decides nothing: it only adds names to the wire format the gateway
emits. ``enforcement.py`` is untouched, so the SDK, the CLI, the audit chain and the
stored decision rows keep the field names they already have.
"""

from __future__ import annotations

from typing import Any

#: Existing key -> the clearer alias added alongside it.
ALIASES: dict[str, str] = {
    "verdict": "applied_verdict",
    "effective_verdict": "would_be_verdict",
}


def with_verdict_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with :data:`ALIASES` filled in from the keys it has.

    A shallow copy, and only top-level keys: a nested ``rules_fired`` entry's
    ``effect`` is a rule's own outcome, not this request's, and aliasing it would
    invent a claim about what took effect that nobody made.

    An alias already present in ``payload`` is left as it is, so a caller that has
    set one deliberately is not overwritten.
    """
    if not isinstance(payload, dict):  # pragma: no cover - defensive
        return payload
    aliased = dict(payload)
    for source, alias in ALIASES.items():
        if source in aliased and alias not in aliased:
            aliased[alias] = aliased[source]
    return aliased


def verdict_headers(result: Any) -> dict[str, str]:
    """The alias headers, matching :data:`ALIASES`.

    Returned separately from the existing ``X-Nometria-Verdict`` /
    ``X-Nometria-Effective-Verdict`` pair so that pair keeps its exact current value
    for anything already reading it.
    """
    return {
        "X-Nometria-Applied-Verdict": getattr(result, "verdict", "") or "",
        "X-Nometria-Would-Be-Verdict": getattr(result, "effective_verdict", "") or "",
    }
