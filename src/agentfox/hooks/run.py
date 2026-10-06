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
"""

from __future__ import annotations

import json

from agentfox import harnesses
from agentfox.harnesses.base import HookOutput
from agentfox.hooks import client


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
                return HookOutput(stdout="{}")
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
        return HookOutput(stdout="", stderr=client.unavailable_message(exc))

    return harnesses.output(harness, event, verdict)


__all__ = ["run"]
