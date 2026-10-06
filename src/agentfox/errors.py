"""The exceptions AgentFox raises into a caller's code, under one base.

There used to be two classes called ``PolicyViolation`` and two called
``ApprovalRequired`` — the SDK's and the LangGraph integration's — so
``except agentfox.PolicyViolation`` did not catch what an ``AgentFoxGuard`` node
raised (#46). There is now one of each, and everything AgentFox refuses with is an
``AgentFoxError``:

* `PolicyViolation` — a decision blocked the call.
* `ApprovalRequired` — a decision held the call for a person; ``approval_id`` is the
  approval to wait on (`AgentFox.wait_for_approval`) and to retry with.
* `agentfox.Blocked` — `auto()` refused a call (also a ``RuntimeError``).

Importing this module opens nothing and imports no client library.
"""

from __future__ import annotations

from typing import Any


class AgentFoxError(Exception):
    """Base of every exception AgentFox raises because a call was refused or held.

    ``result`` is the `EnforcementResult` behind it, never just a message.
    """

    result: Any = None


class PolicyViolation(AgentFoxError):
    """Raised when enforcement blocks. Carries the full decision, never just a message."""

    def __init__(self, result: Any) -> None:
        super().__init__(result.reason or "blocked by policy")
        self.result = result
        self.trace_id = result.trace_id
        self.decision_id = result.decision_id
        self.rules_fired = result.rules_fired
        self.entities = result.entities


class ApprovalRequired(AgentFoxError):
    """Raised when a decision escalates to a human (P2-3)."""

    def __init__(self, result: Any) -> None:
        super().__init__(result.reason or "human approval required")
        self.result = result
        self.approval_id = result.approval_id
        self.trace_id = result.trace_id


__all__ = ["AgentFoxError", "ApprovalRequired", "PolicyViolation"]
