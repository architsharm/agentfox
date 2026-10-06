"""Does a deny on this (harness, event) actually stop the agent?

The question nothing in this product asked. We assert enforcement across nine surfaces
and several integrations, and `langgraph.py` does raise on a block — but nothing
recorded, per integration and per event, whether the verdict is read at a call site
that prevents the action. That is a different claim from "we returned block", and only
one of them is a control.

A competitor learned this the expensive way. Their docs described a harness's turn-end
hook as a working gate while upstream discarded the return value, so every customer
policy on that event enforced nothing, silently, for months. Prose drifted; a table a
test can assert against cannot.

**ABSENT MEANS UNVERIFIED, NOT "BLOCK".** A caller must treat a missing entry as "say
nothing". A hedge rendered in the UI is still a claim, and an unverified claim is what
this module exists to prevent.

The rows themselves live with each adapter (`EventCaps.verified`, with its evidence
class and the harness version it was established against). This module reads them
across the registry: the flat tables `agentfox admin hooks status` prints, and the one
line per event `agentfox admin hooks install` tells the operator.

Rows arrive when somebody runs the probe, and the probe is cheap: install a hook that
denies one sentinel string and allows everything else, then try the sentinel.
"""

from __future__ import annotations

from agentfox import harnesses
from agentfox.harnesses.base import Verified

#: What a deny actually prevents, per canonical event kind, in the reader's noun.
_STOPS = {
    "tool.pre": "stops the call before it runs",
    "tool.post": "does not stop anything; the call has already run",
    "prompt.submit": "stops the turn reaching the model",
}


def _build() -> tuple[
    dict[tuple[str, str], Verified], dict[tuple[str, str], str], dict[str, Verified]
]:
    from agentfox.harnesses.base import KIND_SURFACE

    capability: dict[tuple[str, str], Verified] = {}
    surface: dict[tuple[str, str], str] = {}
    rewrite: dict[str, Verified] = {}
    for adapter in harnesses.all():
        for kind, native in adapter.events.items():
            surface[(adapter.name, native)] = KIND_SURFACE.get(kind, "input")
            caps = adapter.capabilities.get(kind)
            if caps is None:
                continue
            if caps.verified is not None:
                capability[(adapter.name, native)] = caps.verified
            if caps.can_modify and caps.rewrite_verified is not None:
                rewrite[adapter.name] = caps.rewrite_verified
    return capability, surface, rewrite


#: Every verified row, keyed (harness, the harness's own event name).
#: The tables are read off the registered adapters once, at import.
CAPABILITY, EVENT_SURFACE, CAN_REWRITE_INPUT = _build()


def capability_of(harness: str, event: str) -> Verified | None:
    """What a deny does here, or None if nobody has checked."""
    return CAPABILITY.get((harness, event))


def _kind_of(harness: str, event: str) -> str:
    try:
        adapter = harnesses.get(harness)
    except harnesses.UnknownHarness:
        return ""
    return next((kind for kind, native in adapter.events.items() if native == event), "")


def describe(harness: str, event: str) -> str:
    """One line an operator can act on, for the install summary and `doctor`."""
    known = capability_of(harness, event)
    if known is None:
        return (
            f"{harness}/{event}: unverified. The hook will run and record, and whether a "
            "deny stops the call has not been established against this harness — treat it "
            "as observation until it has."
        )
    provenance = f"({known.evidence.lower()}, {known.version})"
    kind = _kind_of(harness, event)
    # The noun matters. "A deny stops the call" is wrong on an event that never sees a
    # call, and "observes only" understates an event that does reach the model. Each
    # event gets the sentence that is true of it.
    if known.capability == "block":
        stops = _STOPS.get(kind, "stops the action")
        return f"{harness}/{event}: a deny {stops} {provenance}."
    if kind == "tool.post":
        return (
            f"{harness}/{event}: the call has already run — a deny cannot withdraw it, "
            f"but the reason does reach the model {provenance}."
        )
    return (
        f"{harness}/{event}: the action proceeds regardless; this event observes only {provenance}."
    )


__all__ = [
    "CAN_REWRITE_INPUT",
    "CAPABILITY",
    "EVENT_SURFACE",
    "Verified",
    "capability_of",
    "describe",
]
