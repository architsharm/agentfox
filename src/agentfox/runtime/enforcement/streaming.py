"""The streaming completion path."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from agentfox.platform.ledger.trace import end_trace
from agentfox.platform.providers import CompletionRequest
from agentfox.runtime.enforcement.completion import (
    release_before_provider_call,
    wants_structured_output,
)
from agentfox.runtime.enforcement.result import StreamEvent


class _StreamingMixin:
    """Enforcer's streaming path. Mixed into :class:`Enforcer`, never used alone."""

    def run_completion_stream(
        self,
        *,
        agent_slug: str | None,
        messages: list[dict[str, Any]],
        model: str = "default",
        provider: str | None = None,
        credential: str | None = None,
        environment: str = "production",
        session_id: str | None = None,
        intent: str | None = None,
        trust_map: dict[str, str] | None = None,
        correlation: dict[str, str] | list[Any] | None = None,
        known_entities: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        mode: str | None = None,
        approval_id: str | None = None,
        passthrough: dict[str, Any] | None = None,
        passthrough_protocol: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Enforced streaming completion.

        Two modes, and the trade-off between them is real rather than cosmetic:

        ``buffered`` (default)
            Accumulate the whole response, run the full post-flight, then release.
            Output enforcement is *identical* to the non-streaming path — nothing can
            leak — at the cost of first-token latency. This is the correct default
            because a DLP control that only inspects the first 200 characters is not
            a DLP control.

        ``windowed``
            Forward chunks as they arrive while running detectors over a growing
            window. First-token latency is preserved, and the honest caveat is that
            **content already forwarded cannot be recalled** — a block terminates the
            stream but does not un-send what preceded it. Offered for latency-critical
            deployments that accept that trade knowingly, never as a silent default.
        """
        mode = mode or self.settings.streaming_mode
        pre = self.preflight(
            agent_slug=agent_slug,
            messages=messages,
            model=model,
            provider=provider,
            credential=credential,
            environment=environment,
            session_id=session_id,
            intent=intent,
            trust_map=trust_map,
            correlation=correlation,
            known_entities=known_entities,
            approval_id=approval_id,
            structured=wants_structured_output(passthrough),
        )
        if evidence is not None:
            self.evidence = evidence
        if pre.stopped:
            if pre.result.verdict == "abstain":
                # An abstention is the reply, not an error: stream it as one.
                yield StreamEvent(kind="delta", delta=pre.result.content or "")
                yield StreamEvent(kind="done", finish_reason="stop", result=pre.result)
                return
            yield StreamEvent(kind="blocked", result=pre.result)
            return

        agent, identity, trace = pre.agent, pre.identity, pre.trace
        tracker, redacted_messages, worst = pre.tracker, pre.messages, pre.result
        release_before_provider_call(self.session)

        request = CompletionRequest(
            messages=redacted_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            passthrough=passthrough,
            passthrough_protocol=passthrough_protocol,
        )

        started = time.perf_counter()
        stream_iter, model_provider, degradation = self.call_provider(
            request, provider=provider, model=model, stream=True
        )
        accumulated: list[str] = []
        # Tool calls the model proposes arrive as fragments keyed by index; they are
        # forwarded as they come and assembled for the record.
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, int] = {}
        finish_reason: str | None = None
        pending: list[StreamEvent] = []
        last_checked = 0
        window = self.settings.stream_window_chars

        for chunk in stream_iter:
            if chunk.usage:
                usage = chunk.usage
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.tool_calls:
                _merge_tool_calls(tool_calls, chunk.tool_calls)
                call_event = StreamEvent(kind="delta", tool_calls=chunk.tool_calls)
                if mode == "windowed":
                    yield call_event
                else:
                    pending.append(call_event)
            if not chunk.delta:
                continue
            accumulated.append(chunk.delta)
            event = StreamEvent(kind="delta", delta=chunk.delta)

            if mode == "windowed":
                yield event
                text = "".join(accumulated)
                # Re-check only when enough new content has arrived to be worth the
                # detector pass; every chunk would blow the latency budget.
                if len(text) - last_checked >= window:
                    last_checked = len(text)
                    interim = self.evaluate(
                        agent=agent,
                        identity=identity,
                        content=text,
                        surface="output",
                        trace=trace,
                        taint_source="none",
                        intent=intent,
                        tracker=tracker,
                        persist=False,
                    )
                    if interim.blocked:
                        interim.trace_id = trace.id
                        end_trace(self.session, trace, verdict="block", status="blocked")
                        yield StreamEvent(kind="blocked", result=interim)
                        return
            else:
                pending.append(event)

        provider_ms = (time.perf_counter() - started) * 1000
        from agentfox.platform.providers import CompletionResponse, estimate_cost

        response = CompletionResponse(
            text="".join(accumulated),
            model=model,
            provider=model_provider.key,
            usage=usage,
            # A streamed answer costs what a whole one does; it used to be recorded as 0.
            cost_usd=estimate_cost(
                model, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
            ),
            tool_calls=[tool_calls[i] for i in sorted(tool_calls)],
        )

        final, released = self._finish_completion(
            agent=agent,
            agent_slug=agent_slug,
            identity=identity,
            trace=trace,
            tracker=tracker,
            worst=worst,
            response=response,
            model=model,
            model_provider=model_provider,
            provider_ms=provider_ms,
            intent=intent,
            schema=schema,
        )

        if mode == "buffered":
            if final.blocked:
                yield StreamEvent(kind="blocked", result=final)
                return
            # Release the (possibly redacted) text. Redaction is why this is not a
            # simple replay of `pending`: post-flight may have rewritten the content.
            text = released.text if released else ""
            if text == "".join(accumulated):
                yield from pending
            else:
                yield StreamEvent(kind="delta", delta=text)
                yield from (e for e in pending if e.tool_calls)
        elif final.blocked:
            # Windowed mode: the tail was blocked after content had already been sent.
            yield StreamEvent(kind="blocked", result=final)
            return

        yield StreamEvent(
            kind="done", finish_reason=finish_reason or "stop", usage=usage, result=final
        )


def _merge_tool_calls(into: dict[int, dict[str, Any]], fragments: list[dict[str, Any]]) -> None:
    """Assemble OpenAI-style streamed tool-call fragments into whole calls."""
    for fragment in fragments:
        index = int(fragment.get("index", 0))
        call = into.setdefault(
            index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )
        call["id"] = fragment.get("id") or call["id"]
        function = fragment.get("function") or {}
        call["function"]["name"] += function.get("name") or ""
        call["function"]["arguments"] += function.get("arguments") or ""
