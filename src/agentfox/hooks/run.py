"""One hook invocation: payload in, reply out. What `agentfox hooks run` executes.

Everything in this path runs in a process the harness creates and destroys per tool
call, so it does the least possible: parse with the harness's adapter, ask the daemon,
render with the adapter. Measured against a warm daemon, the round trip is about 6ms;
the same work without one is 3.9 seconds, because `import agentfox` is.

Nothing here knows which harness is calling. The adapter, found by name in the
registry, owns the payload shape and the reply shape.

Every failure exits 0: a hook that cannot parse its input, or cannot reach the
daemon, must not take the agent down with it. It says so on stderr, where the harness
shows it.

Beside the daemon's verdict, the delivery policies (`capabilities/delivery`) run here,
in the hook process, on the session's own history. The daemon decides whether a call
is *allowed*; they decide whether the agent is about to lose work it already got
right. A daemon refusal always wins. ``AGENTFOX_DELIVERY=off`` disables them;
``AGENTFOX_DELIVERY=only`` runs them without asking the daemon at all (a sandbox or
benchmark container with no control plane in it).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agentfox import harnesses
from agentfox.capabilities import delivery
from agentfox.harnesses.base import AgentEvent, Decision, HookOutput
from agentfox.hooks import client


def _mode() -> str:
    mode = os.environ.get("AGENTFOX_DELIVERY", "on").strip().lower()
    return "off" if mode in {"off", "0", "false", "no"} else mode


def _delivery_root() -> Path | None:
    if _mode() == "off":
        return None
    override = os.environ.get("AGENTFOX_DELIVERY_STATE")
    if override:
        return Path(override)
    from agentfox.hooks.protocol import socket_path

    return socket_path().parent.parent / "delivery"


def _delivery(event: AgentEvent) -> Decision | None:
    """Update the session's delivery state for this event; a decision if one is due."""
    root = _delivery_root()
    if root is None or not event.session_id:
        return None
    state = delivery.load(root, event.session_id)
    call = delivery.Call(tool=event.canonical_tool, arguments=event.arguments)
    nudge = None
    if event.kind == "prompt.submit":
        delivery.on_task(state, event.content)
    elif event.kind == "tool.pre":
        nudge = delivery.before_call(state, call)
    elif event.kind == "tool.post":
        delivery.after_call(state, call)
    elif event.kind == "stop":
        nudge = delivery.at_stop(
            state,
            delivery.Stop(reentered=event.reentered, background_tasks=event.background_tasks),
        )
    else:
        return None
    delivery.save(root, event.session_id, state)
    if nudge is None:
        return None
    if nudge.action == "deny" or event.kind == "stop":
        # At a stop, a refusal is how the instruction reaches the agent: it keeps going.
        return Decision.deny(nudge.text, nudge.rules)
    return Decision.with_context("AgentFox: " + nudge.text)


def run(harness: str, agent: str, raw: str) -> HookOutput:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        return HookOutput(stdout="", stderr=f"agentfox: could not parse the hook payload: {exc}")

    try:
        adapter = harnesses.get(harness)
    except harnesses.UnknownHarness as exc:
        return HookOutput(stdout="", stderr=f"agentfox: {exc}")
    event = adapter.parse(payload)

    try:
        nudge = _delivery(event)
    except Exception as exc:  # never fail the agent's call over a delivery policy
        nudge = None
        sys.stderr.write(f"agentfox: delivery policies skipped: {exc}\n")
    if event.kind == "stop" or _mode() == "only":
        # Nothing for the daemon to authorise: the agent is ending its turn (or there
        # is no daemon by design).
        return adapter.render(nudge or Decision.allow(), event)

    slug = agent or event.session_id or "unknown"
    try:
        if event.checks_content:
            # A tool's result and the operator's turn carry text, not a call to
            # authorise. Same daemon, same policy set, different surface — which is
            # what makes nine surfaces a real claim at a hook rather than an
            # architecture diagram.
            if not event.content.strip():
                # Nothing to check. Say nothing rather than run the engine over an
                # empty string and record a decision about it.
                return adapter.render(nudge, event) if nudge else HookOutput(stdout="{}")
            verdict = client.guard_content(
                agent=slug,
                surface=event.surface,
                content=event.content,
                tool=event.tool,
            )
        else:
            verdict = client.guard_tool_call(
                agent=slug,
                tool=event.tool,
                arguments=event.arguments,
            )
    except client.DaemonUnavailable as exc:
        message = client.unavailable_message(exc)
        if nudge is None:
            return HookOutput(stdout="", stderr=message)
        out = adapter.render(nudge, event)
        return HookOutput(out.stdout, message, out.exit_code, out.decision)

    out = harnesses.output(harness, event, verdict)
    if nudge is not None and out.decision.kind == "allow":
        return adapter.render(nudge, event)
    return out


__all__ = ["run"]
