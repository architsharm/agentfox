"""The full inline path for a completion: preflight, the provider call with its
fallback ladder, post-flight, answerability, and trace correlation.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from agentfox.capabilities.detection import TaintTracker
from agentfox.capabilities.detection.taint import _flatten
from agentfox.capabilities.grounding.answerability import (
    classify_answerability,
    detect_over_refusal,
    get_boundary,
    verify_boundary,
)
from agentfox.core.models import Agent, Decision, TaintTag, Trace
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.findings import raise_finding
from agentfox.platform.ledger.trace import (
    ATTR_AGENT,
    ATTR_REQUEST_MODEL,
    ATTR_SYSTEM,
    add_span,
    end_trace,
    start_trace,
)
from agentfox.platform.providers import CompletionRequest, CompletionResponse, get_provider
from agentfox.runtime.enforcement.result import (
    EnforcementResult,
    PreflightOutcome,
    ProviderUnavailable,
)
from agentfox.runtime.enforcement.rules import _RANK, _fired_rule
from agentfox.runtime.enforcement.summary import summarize
from agentfox.runtime.reliability import BREAKER, DegradationRecord, FallbackLadder, ProviderAttempt
from agentfox.runtime.reliability import Rung as _Rung
from agentfox.runtime.trace_exporters import trace_exporters

log = logging.getLogger("agentfox.runtime.enforcement")


def release_before_provider_call(session: Any) -> None:
    """Commit what preflight wrote before waiting on the model.

    Preflight touches the agent row (``last_seen_at``) and opens the trace. Holding
    that transaction across a model call of several seconds holds the agent's row
    lock with it, so every other request for the same agent waits behind the model
    — and on Postgres fails once the 5 s ``lock_timeout`` passes. The records are
    complete facts on their own; committing them first costs nothing.

    Only a transaction the session began on its own is committed. One a caller
    opened deliberately (``with session.begin():``, a savepoint) is theirs to end.
    """
    from sqlalchemy.orm import SessionTransactionOrigin

    transaction = session.get_transaction()
    if transaction is None or session.in_nested_transaction():
        return
    if transaction.origin is SessionTransactionOrigin.AUTOBEGIN:
        session.commit()


def wants_structured_output(passthrough: dict[str, Any] | None) -> bool:
    """Whether the caller asked for JSON (OpenAI ``response_format``), not prose."""
    fmt = (passthrough or {}).get("response_format")
    return isinstance(fmt, dict) and fmt.get("type") in ("json_schema", "json_object")


class _CompletionMixin:
    """Enforcer's inline completion path. Mixed into :class:`Enforcer`, never used alone."""

    def _answerability_gate(
        self,
        agent: Agent | None,
        trace: Trace,
        messages: list[dict[str, Any]],
        known_entities: list[str] | None = None,
    ) -> EnforcementResult | None:
        """Refuse to generate when the question is outside the declared boundary.

        Returns None when there is no boundary, when the question is answerable, or
        when the boundary is in observe mode. The observe case still records the
        counterfactual, so a team can see what enforcement *would* have refused before
        turning it on — which is the only responsible way to ship a control whose
        false positives are refusals.
        """
        boundary = get_boundary(self.session, agent.id if agent else None)
        if boundary is None:
            return None
        question = next(
            (
                _flatten(m.get("content"))
                for m in reversed(messages)
                if str(m.get("role")) == "user"
            ),
            "",
        )
        if not question.strip():
            return None

        verdict = classify_answerability(question, boundary, known_entities=known_entities)
        if verdict.answerable:
            # The deterministic check is precise (95.1%) but low-recall (38.1%),
            # missing 8.4% of contested questions. An enabled judgment tier may
            # add an abstention it found; it can never remove one, so the
            # deterministic verdict above stays authoritative where it fired.
            # No-ops entirely when no judgment tier is enabled.
            from agentfox.capabilities.judgment.answerability import augment as _judge_answerability

            verdict = _judge_answerability(verdict, question)
        if verdict.answerable:
            return None

        rule = _fired_rule(
            f"answerability.{verdict.abstention_kind}",
            "abstain",
            verdict.reasons[0].get("reason")
            or f"question is {verdict.question_type}, outside the declared boundary",
            severity="medium",
            controls=["NOM-RTG-11"],
        )
        chain.append(
            self.session,
            action=f"answerability.{verdict.abstention_kind}",
            actor_type="agent",
            actor_id=agent.id if agent else None,
            subject_type="trace",
            subject_id=trace.id,
            payload={"question_type": verdict.question_type, "reasons": verdict.reasons},
        )
        result = EnforcementResult(
            # `abstain` sits between redact and escalate in the lattice: it withholds
            # the answer without treating the user as an adversary.
            verdict="abstain" if verdict.should_abstain else "allow",
            effective_verdict="abstain",
            mode=boundary.mode,
            trace_id=trace.id,
            rules_fired=[rule],
            reason=rule["reason"],
            content=verdict.response,
        )
        result.taint["answerability"] = verdict.to_json()
        # Recorded like any other decision, watching or not, so the abstention is on
        # the run and counted where wrong answers are counted.
        self.session.add(
            Decision(
                trace_id=trace.id,
                agent_id=agent.id if agent else None,
                surface="input",
                verdict=result.verdict,
                rules_fired_json=[{**rule, "mode": boundary.mode}],
                mode=boundary.mode,
                taint_summary_json={"answerability": verdict.to_json()},
            )
        )
        return result if verdict.should_abstain else None

    def _answerability_postflight(self, agent: Agent | None, trace: Trace, answer: str) -> None:
        boundary = get_boundary(self.session, agent.id if agent else None)
        if boundary is None or not answer:
            return
        verdict = classify_answerability(answer, boundary)
        for breach in verify_boundary(answer, verdict, boundary):
            raise_finding(
                self.session,
                type="boundary_breach",
                severity="medium",
                title=f"Answer exceeded the declared knowledge boundary: {breach['breach']}",
                subject_type="agent",
                subject_id=agent.id if agent else None,
                evidence={**breach, "trace_id": trace.id},
                control_keys=["NOM-RTG-11"],
                fingerprint_parts=(breach.get("breach"),),
            )
        detect_over_refusal(
            self.session,
            answer=answer,
            verdict=verdict,
            agent_id=agent.id if agent else None,
            trace_id=trace.id,
        )

    def _correlate(self, trace, correlation) -> None:
        """Record the join key to LangSmith/Langfuse. Never fails the request.

        Correlation is a convenience for the humans debugging later; it must not be
        able to take down the path it is describing.
        """
        try:
            for exporter in trace_exporters():
                exporter.link(self.session, trace.id, correlation)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("correlation link skipped: %s", exc)

    def _push_correlation(self, trace, result, agent_slug: str | None) -> None:
        try:
            for exporter in trace_exporters():
                exporter.push(
                    self.session,
                    trace.id,
                    verdict=result.verdict,
                    effective_verdict=result.effective_verdict,
                    rules=[r.get("rule_id", "") for r in result.rules_fired],
                    agent_slug=agent_slug,
                )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("correlation push skipped: %s", exc)

    def preflight(
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
        approval_id: str | None = None,
        structured: bool = False,
    ) -> PreflightOutcome:
        """Steps 2-6 of the request path, shared by buffered and streaming calls.

        Extracted so that streaming cannot drift from non-streaming enforcement. A
        streaming path that quietly skips a check would break the guarantee that
        every surface is enforced the same way.
        """
        self.reset_ledger()
        agent, identity, _is_shadow = self.resolve(
            agent_slug, credential, environment=environment, model=model
        )

        # A killed or quarantined agent never reaches the model.
        control = self._control_verdict(agent)
        if control is not None:
            trace = start_trace(
                self.session,
                agent_id=agent.id if agent else None,
                agent_slug=agent.slug if agent else agent_slug,
                session_id=session_id,
                environment=environment,
                intent=intent,
                model=model,
                provider=provider or self.settings.default_provider,
            )
            self._correlate(trace, correlation)
            control.trace_id = trace.id
            end_trace(self.session, trace, verdict=control.verdict, status="blocked")
            self._push_correlation(trace, control, agent.slug if agent else agent_slug)
            return PreflightOutcome(
                agent=agent, identity=identity, trace=trace, result=control, stopped=True
            )

        trace = start_trace(
            self.session,
            agent_id=agent.id if agent else None,
            agent_slug=agent.slug if agent else agent_slug,
            session_id=session_id,
            environment=environment,
            intent=intent,
            model=model,
            provider=provider or self.settings.default_provider,
        )

        self._correlate(trace, correlation)

        # Hard caps, checked before the model call rather than after the spend.
        budget = self._budget_gate(agent, trace)
        if budget is not None:
            end_trace(self.session, trace, verdict="block", status="blocked")
            self._push_correlation(trace, budget, agent.slug if agent else agent_slug)
            return PreflightOutcome(
                agent=agent, identity=identity, trace=trace, result=budget, stopped=True
            )

        # Answerability, before generation. Every competitor scores the answer
        # after it exists, which cannot prevent fabrication — by then the number has
        # been invented, and a confident wrong number scored at 0.4 is still a
        # confident wrong number in front of a user.
        # Only a reply to a person can abstain. A call asking for structured output
        # (a classifier, an extraction, the app's own guardrail) is not answering the
        # question, and a sentence where its JSON should be would break the caller.
        abstain = (
            None if structured else self._answerability_gate(agent, trace, messages, known_entities)
        )
        if abstain is not None:
            end_trace(self.session, trace, verdict=abstain.verdict, status="abstained")
            self._push_correlation(trace, abstain, agent.slug if agent else agent_slug)
            return PreflightOutcome(
                agent=agent, identity=identity, trace=trace, result=abstain, stopped=True
            )

        tracker = TaintTracker(trace_id=trace.id)
        tracker.mark_messages(messages, trust_map)
        for mark in tracker.marks:
            self.session.add(
                TaintTag(
                    trace_id=trace.id,
                    path=mark.path,
                    source=mark.source,
                    trust=mark.trust,
                    propagated_from=mark.propagated_from,
                )
            )

        worst = EnforcementResult()
        redacted_messages = list(messages)

        for i, message in enumerate(messages):
            text = _flatten(message.get("content"))
            if not text.strip():
                continue
            role = str(message.get("role", "user"))
            source = (trust_map or {}).get(str(i)) or {
                "system": "none",
                "developer": "none",
                "assistant": "none",
                "user": "user",
                "tool": "tool_result",
                "function": "tool_result",
            }.get(role, "user")
            if source == "none":
                # The application's own text — its system and developer prompts, and
                # replies it already got (checked as output when they were made). They
                # are not user input, and scanning them as such blocks any app whose
                # instructions talk about instructions: a guardrail prompt describing
                # jailbreaks reads as one. Untrusted text an app puts in these roles
                # (retrieved passages in a system prompt) is marked with
                # X-AgentFox-Trust and is checked under that source instead.
                continue
            surface = {
                "tool_result": "tool_result",
                "retrieved": "retrieved",
                "subagent": "tool_result",
            }.get(source, "input")

            outcome = self.evaluate(
                agent=agent,
                identity=identity,
                content=text,
                surface=surface,
                trace=trace,
                taint_source=source,
                intent=intent,
                tracker=tracker,
                # A retry of a held message presents its approval; the message
                # it was granted for is the one it releases.
                approval_id=approval_id,
            )
            if outcome.content is not None:
                redacted_messages[i] = {**message, "content": outcome.content}
            if self._severity(outcome) >= self._severity(worst):
                worst = outcome

        worst.trace_id = trace.id
        if not trace.summary:
            asked = next((m for m in reversed(messages) if m.get("role") == "user"), None)
            trace.summary = summarize(_flatten(asked.get("content"))) if asked else None
        if worst.blocked or worst.escalated:
            end_trace(self.session, trace, verdict=worst.verdict, status="blocked")
            return PreflightOutcome(
                agent=agent,
                identity=identity,
                trace=trace,
                tracker=tracker,
                messages=redacted_messages,
                result=worst,
                stopped=True,
            )

        return PreflightOutcome(
            agent=agent,
            identity=identity,
            trace=trace,
            tracker=tracker,
            messages=redacted_messages,
            result=worst,
        )

    def call_provider(
        self,
        request: CompletionRequest,
        *,
        provider: str | None,
        model: str,
        ladder: FallbackLadder | None = None,
        stream: bool = False,
    ):
        """Call a provider with circuit breaking and a degradation ladder.

        Returns ``(response_or_iterator, DegradationRecord)``. Degradation is recorded
        rather than silently absorbed: an answer served by a smaller model did not come
        from the model the agent was evaluated against, and a baseline that quietly
        covers a different model is worthless.
        """
        preferred = _Rung(provider or self.settings.default_provider, model)
        ladder = ladder or FallbackLadder.parse(self.settings.fallback_chain)
        record = DegradationRecord()
        last_error: Exception | None = None

        for index, rung in enumerate([preferred, *ladder.rungs]):
            key = f"{rung.provider}:{rung.model}"
            if not BREAKER.allows(key):
                record.attempts.append(
                    ProviderAttempt(
                        rung.provider,
                        rung.model,
                        ok=False,
                        error="circuit open — failing fast",
                        breaker_state=BREAKER.state_of(key),
                    )
                )
                continue
            try:
                model_provider = get_provider(rung.provider)
            except KeyError as exc:
                record.attempts.append(
                    ProviderAttempt(rung.provider, rung.model, ok=False, error=str(exc))
                )
                continue

            attempt_request = CompletionRequest(
                messages=request.messages,
                model=rung.model or request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
                passthrough=request.passthrough,
                passthrough_protocol=request.passthrough_protocol,
            )
            try:
                result = (
                    model_provider.stream(attempt_request)
                    if stream
                    else model_provider.complete(attempt_request)
                )
            except Exception as exc:  # noqa: BLE001 - any provider failure trips the breaker
                BREAKER.record_failure(key)
                last_error = exc
                record.attempts.append(
                    ProviderAttempt(
                        rung.provider,
                        rung.model,
                        ok=False,
                        error=str(exc),
                        breaker_state=BREAKER.state_of(key),
                    )
                )
                continue

            BREAKER.record_success(key)
            record.attempts.append(ProviderAttempt(rung.provider, rung.model, ok=True))
            record.served_by = key
            record.degraded = index > 0
            return result, model_provider, record

        raise ProviderUnavailable(
            f"every provider on the ladder failed or is circuit-open: "
            f"{[a.provider + ':' + a.model for a in record.attempts]}"
        ) from last_error

    def _finish_completion(
        self,
        *,
        agent,
        agent_slug,
        identity,
        trace,
        tracker,
        worst,
        response,
        model,
        model_provider,
        provider_ms,
        intent,
        schema,
        severity=None,
        reask: Callable[[str, str], Any] | None = None,
    ) -> tuple[EnforcementResult, Any]:
        """Post-flight, span, budget and trace close — shared by both paths.

        ``reask(previous_text, instruction)`` returns a second completion, or None.
        Given only on the buffered path: a streamed answer has already reached the
        caller, so there is nothing left to replace.
        """
        rank = severity or self._severity
        add_span(
            self.session,
            trace,
            kind="llm",
            name=f"{model_provider.key}.complete",
            attributes={
                ATTR_SYSTEM: model_provider.key,
                ATTR_REQUEST_MODEL: model,
                ATTR_AGENT: agent.slug if agent else agent_slug,
                "gen_ai.usage.input_tokens": response.usage.get("input_tokens", 0),
                "gen_ai.usage.output_tokens": response.usage.get("output_tokens", 0),
                "agentfox.output": response.text,
            },
            duration_ms=provider_ms,
        )

        outbound = self.evaluate(
            agent=agent,
            identity=identity,
            content=response.text,
            surface="output",
            trace=trace,
            taint_source="none",
            intent=intent,
            schema=schema,
            tracker=tracker,
        )
        if reask is not None and outbound.blocked and outbound.reask_instruction:
            outbound, response = self._reask_once(
                reask,
                outbound=outbound,
                response=response,
                agent=agent,
                identity=identity,
                trace=trace,
                tracker=tracker,
                intent=intent,
                schema=schema,
                model_provider=model_provider,
            )
        if outbound.content is not None:
            response.text = outbound.content
        final = outbound if rank(outbound) >= rank(worst) else worst
        final.trace_id = trace.id

        # Post-flight boundary verification and the counter-metric. Both
        # produce findings and neither blocks — an over-refusing agent is uninstalled
        # faster than a hallucinating one, so this side of the control never enforces.
        self._answerability_postflight(agent, trace, response.text)

        self._charge_budget(agent, response)
        end_trace(
            self.session,
            trace,
            verdict=final.verdict,
            status="ok",
            usage=response.usage,
            cost_usd=response.cost_usd,
        )
        self._push_correlation(trace, final, agent.slug if agent else agent_slug)
        return final, (None if final.blocked else response)

    def _reask_once(
        self,
        reask: Callable[[str, str], Any],
        *,
        outbound: EnforcementResult,
        response: Any,
        agent,
        identity,
        trace,
        tracker,
        intent,
        schema,
        model_provider,
    ) -> tuple[EnforcementResult, Any]:
        """Ask the model once more with the blocking rules' correction.

        One retry, never a loop: a model that repeats the problem gets the block.
        Both answers are evaluated and recorded, so the audit trail shows that a
        first answer was refused and why, even when the caller got the second.
        """
        started = time.perf_counter()
        try:
            retry = reask(response.text or "", outbound.reask_instruction)
        except Exception as exc:  # noqa: BLE001 - a failed retry keeps the original block
            log.warning("re-ask failed, keeping the block: %s", exc)
            return outbound, response
        if retry is None:
            return outbound, response
        add_span(
            self.session,
            trace,
            kind="llm",
            name=f"{model_provider.key}.reask",
            attributes={"agentfox.reask_rules": [r.get("rule_id") for r in outbound.rules_fired]},
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        second = self.evaluate(
            agent=agent,
            identity=identity,
            content=retry.text,
            surface="output",
            trace=trace,
            taint_source="none",
            intent=intent,
            schema=schema,
            tracker=tracker,
        )
        if second.blocked:
            return second, response
        second.taint = {
            **second.taint,
            "reask": {
                "fixed": True,
                "refused_rules": [r.get("rule_id") for r in outbound.rules_fired],
            },
        }
        return second, retry

    def run_completion(
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
        approval_id: str | None = None,
        passthrough: dict[str, Any] | None = None,
        passthrough_protocol: str | None = None,
    ) -> tuple[EnforcementResult, Any]:
        """The complete request path. Returns (result, response|None).

        ``passthrough`` is the client's request beyond messages and model, forwarded
        to a provider speaking ``passthrough_protocol`` (see `CompletionRequest`).
        """
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
            structured=wants_structured_output(passthrough),
            known_entities=known_entities,
            approval_id=approval_id,
        )
        if evidence is not None:
            self.evidence = evidence
        if pre.stopped:
            if pre.result.verdict == "abstain":
                # An abstention is an answer: the agent says it cannot know rather
                # than guessing, and the caller receives that as the reply.
                return pre.result, CompletionResponse(text=pre.result.content or "", model=model)
            return pre.result, None

        agent, identity, trace = pre.agent, pre.identity, pre.trace
        tracker, redacted_messages, worst = pre.tracker, pre.messages, pre.result
        release_before_provider_call(self.session)

        def severity(result: EnforcementResult) -> tuple[int, int]:
            return (_RANK[result.verdict], _RANK[result.effective_verdict])

        # --- 7. provider call --------------------------------------------
        started = time.perf_counter()
        response, model_provider, degradation = self.call_provider(
            CompletionRequest(
                messages=redacted_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                passthrough=passthrough,
                passthrough_protocol=passthrough_protocol,
            ),
            provider=provider,
            model=model,
        )
        provider_ms = (time.perf_counter() - started) * 1000
        worst.taint = {**worst.taint, "degradation": degradation.to_json()}
        return self._finish_completion(
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
            severity=severity,
            reask=lambda previous, instruction: model_provider.complete(
                CompletionRequest(
                    messages=[
                        *redacted_messages,
                        {"role": "assistant", "content": previous},
                        {"role": "user", "content": instruction},
                    ],
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    passthrough=passthrough,
                    passthrough_protocol=passthrough_protocol,
                )
            ),
        )
