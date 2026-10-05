"""The enforcement orchestrator — PRD §9.3, the request path.

This is where the six pillars stop being separate modules and become one product.
Every inline surface (gateway proxy, direct guard endpoints, SDK, red-team runner)
goes through this class, which is what makes the guarantees hold uniformly:

    identity resolution (P1-2, P2-1)
      -> taint annotation (P3-4)
      -> budgeted detector pipeline (P3-1/2/3/5, P3-6)
      -> capability check (P2-2)
      -> policy decision (P6-1)
      -> escalation to a human (P2-3)
      -> provider call (X-2)
      -> post-flight on the response (P3-2, P3-9, P4-3)
      -> trace, audit chain, findings (P5-1, P5-2)

Two invariants are enforced here rather than assumed:

* **No block without a reason.** Every verdict carries the rule that produced it and
  a human-readable explanation (principle X-4). A guardrail that blocks silently is
  a bug, not a strict configuration.
* **Observe by default.** Enforcement is something a customer turns on deliberately,
  after simulating it. A tool that starts blocking the moment it is installed gets
  uninstalled the same week (PRD R3).

The package, by stage:

* ``enforcer``   — :class:`Enforcer`: identity resolution and the core ``evaluate()``
* ``surfaces``   — content, conversation window, memory, completion, reasoning,
  file and inter-agent message surfaces
* ``tool_calls`` — the tool-call guard and the risks ``evaluate()`` reads for it
* ``checks``     — evidence, disclosure, sycophancy, commitment, trajectory and
  context-integrity checks
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
