"""Delivery policies: keep a coding agent from losing a solution it already reached.

A governance hook usually answers "may this happen?". These policies answer a
different question at the same hook: "is the agent about to throw away work that
was right?". The failures they target are procedural, not capability gaps. The
agent writes a working server and stops, and the server dies with the agent's
shell. It opens the only copy of a damaged database before copying it. It applies
the replacements it was asked for, then runs a formatter over protected bytes.

Each policy pairs an **eligibility** test over the task text, read once at
prompt submission, with a **runtime** test over what the agent has actually run.
It intervenes only when both hold, and then it does one of two things:

* ``deny``: refuse a tool call that would destroy evidence or deployed state.
* ``instruct``: when the agent tries to stop, send it back once with a short,
  specific instruction. Never a generic "check your work": generic
  reconsideration does not help (Huang et al., 2024; FIRE, arXiv 2609.26048).

Everything here is standard library only. It runs inside the hook process,
which the harness starts and kills on every call.
"""

from __future__ import annotations

from agentfox.capabilities.delivery.policies import (
    POLICIES,
    Call,
    Nudge,
    Policy,
    Stop,
    after_call,
    at_stop,
    before_call,
    on_task,
)
from agentfox.capabilities.delivery.state import SessionState, load, save

__all__ = [
    "POLICIES",
    "Call",
    "Nudge",
    "Policy",
    "SessionState",
    "Stop",
    "after_call",
    "at_stop",
    "before_call",
    "load",
    "on_task",
    "save",
]
