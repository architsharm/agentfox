"""The provenance a policy rule reasons over, as distinct from the provenance recorded.

Two decisions sit between the taint tracker and a rule like ``taint_exceeds: user``,
and both are made here, once, so the live path (`enforcement.py`) and replay
(`policy/simulate.py`) cannot disagree about them:

* **Scope** (`Settings.taint_scope`). ``session`` reads the worst provenance anywhere
  in the run so far together with the call's own arguments; ``argument`` reads only
  the arguments. The tracker always records the session value, so the record of a
  call never changes with the setting — only what policy is shown does. The scope in
  force is written onto the decision (``taint["scope"]``) so a replay months later
  reasons the way the live call did, not the way today's setting would.

* **An explicit grant.** A capability whose ``max_taint`` is above the default
  (``user``) is a person's statement that this agent may call this tool with
  arguments of that provenance. When the call's provenance is within it, the
  taint rules do not overrule the grant: the grant is the more specific declaration,
  and a rule that escalates every call the grant was written to allow makes the
  grant meaningless. Provenance within the grant is presented to policy as ``user``,
  the level every grant accepts. Provenance beyond it is presented as it is, so a
  grant up to ``tool_result`` still escalates an argument that came from memory.

  This deliberately does not extend to ``composition.escalation``. A grant's
  ``max_taint`` says what *class* of content may reach the tool; composition is about
  *which tool* produced it — a lower-impact tool's output silently becoming a
  higher-impact tool's input — and no grant on the consuming tool speaks to that.
  Declaring the producing tool's output trusted (`agentfox declare tool X
  --output-trust trusted`) is how an operator says that flow is intended.
"""

from __future__ import annotations

from typing import Any

from agentfox.core.vocab import taint_rank

#: The provenance every grant accepts without saying so (the column default).
BASELINE = "user"


def _worst(sources: Any) -> str:
    worst = "none"
    for source in sources:
        if taint_rank(str(source)) > taint_rank(worst):
            worst = str(source)
    return worst


def grant_ceiling(capability: dict[str, Any] | None) -> str | None:
    """The provenance a matched grant explicitly accepts, or None.

    None unless a grant matched, was not exceeded on its own terms, and names a level
    above the baseline. A grant at the default ``user`` declares nothing about
    untrusted content, so it has nothing to say to a taint rule.
    """
    capability = capability or {}
    if not capability.get("capability_id") or not capability.get("granted", False):
        return None
    if capability.get("taint_violation"):
        return None
    ceiling = str(capability.get("max_taint") or BASELINE)
    if taint_rank(ceiling) <= taint_rank(BASELINE):
        return None
    return ceiling


def policy_taint(taint: dict[str, Any], capability: dict[str, Any] | None) -> dict[str, Any]:
    """The taint summary as the policy engine should see it. Never mutates ``taint``."""
    view = dict(taint or {})
    arguments = {str(k): str(v) for k, v in (view.get("arguments") or {}).items()}
    if view.get("scope") == "argument":
        view["max_source"] = _worst(arguments.values())

    ceiling = grant_ceiling(capability)
    if ceiling is None:
        return view
    actual = _worst([view.get("max_source", "none"), *arguments.values()])
    if taint_rank(actual) > taint_rank(ceiling):
        return view

    def clamp(source: str) -> str:
        return BASELINE if taint_rank(source) > taint_rank(BASELINE) else source

    view["max_source"] = clamp(str(view.get("max_source", "none")))
    view["arguments"] = {path: clamp(source) for path, source in arguments.items()}
    view["accepted_by_grant"] = {
        "capability_id": (capability or {}).get("capability_id"),
        "max_taint": ceiling,
        "provenance": actual,
    }
    return view


__all__ = ["BASELINE", "grant_ceiling", "policy_taint"]
