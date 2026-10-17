"""The enforcement orchestrator — the request path.

This is where the six pillars stop being separate modules and become one product.
Every inline surface (gateway proxy, direct guard endpoints, SDK, red-team runner)
goes through this class, which is what makes the guarantees hold uniformly:

    identity resolution
      -> taint annotation
      -> budgeted detector pipeline
      -> capability check
      -> policy decision
      -> escalation to a human
      -> provider call
      -> post-flight on the response
      -> trace, audit chain, findings

Two invariants are enforced here rather than assumed:

* **No block without a reason.** Every verdict carries the rule that produced it and
  a human-readable explanation. A guardrail that blocks silently is
  a bug, not a strict configuration.
* **Observe by default.** Enforcement is something a customer turns on deliberately,
  after simulating it. A tool that starts blocking the moment it is installed gets
  uninstalled the same week.

The package, by stage:

* ``enforcer``   — :class:`Enforcer`: identity resolution and the core ``evaluate()``
* ``surfaces``   — content, conversation window, memory, completion, reasoning,
  file and inter-agent message surfaces
* ``tool_calls`` — the tool-call guard and the risks ``evaluate()`` reads for it
* ``runtime/checks.py`` (beside this package) names the modules whose registered
  checks ``evaluate()`` runs: evidence, disclosure, commitment, context integrity,
  control flow, sycophancy and trajectory, then the business ladders. The checks live
  in the capabilities that own them (``platform/checks.py`` is the registry)
* ``completion`` — preflight, the provider call, post-flight and correlation
* ``streaming``  — the streaming completion path
* ``limits``     — kill switch and spend budgets
* ``findings``   — persisting detector runs, degradation and findings
* ``rules``      — fallback policies, verdict ranks and fired-rule records
* ``result``     — :class:`EnforcementResult` and the other result types
"""

from agentfox.runtime.enforcement.enforcer import Enforcer
from agentfox.runtime.enforcement.result import (
    EnforcementResult,
    PreflightOutcome,
    ProviderUnavailable,
    StreamEvent,
)
from agentfox.runtime.enforcement.rules import (
    _CAPABILITY_REFUSAL_RULE_IDS,
    RISK_CODE_RULE_IDS,
    _fallback_policies,
)

__all__ = [
    "RISK_CODE_RULE_IDS",
    "_CAPABILITY_REFUSAL_RULE_IDS",
    "EnforcementResult",
    "Enforcer",
    "PreflightOutcome",
    "ProviderUnavailable",
    "StreamEvent",
    "_fallback_policies",
]
