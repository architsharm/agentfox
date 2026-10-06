"""The streaming completion path."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from agentfox.prove.audit.trace import end_trace
from agentfox.providers import CompletionRequest
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
        )
        if evidence is not None:
            self.evidence = evidence
        if pre.stopped:
            yield StreamEvent(kind="blocked", result=pre.result)
            return

        agent, identity, trace = pre.agent, pre.identity, pre.trace
        tracker, redacted_messages, worst = pre.tracker, pre.messages, pre.result

        request = CompletionRequest(
            messages=redacted_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        started = time.perf_counter()
        stream_iter, model_provider, degradation = self.call_provider(
            request, provider=provider, model=model, stream=True
        )
        accumulated: list[str] = []
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
        from agentfox.providers import CompletionResponse

        response = CompletionResponse(
            text="".join(accumulated),
            model=model,
            provider=model_provider.key,
            usage=usage,
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
        elif final.blocked:
            # Windowed mode: the tail was blocked after content had already been sent.
            yield StreamEvent(kind="blocked", result=final)
            return

        yield StreamEvent(
            kind="done", finish_reason=finish_reason or "stop", usage=usage, result=final
        )
