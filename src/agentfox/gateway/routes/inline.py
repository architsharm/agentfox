"""Inline enforcement routes (X-1a, X-1b, X-1c).

Drop-in by design (principle X-1): point an existing OpenAI or Anthropic client's
``base_url`` at this service and enforcement, tracing and audit start working with no
code change. That is what NFR-8's ten-minute time-to-first-value requires — a
governance product that needs a re-architecture never gets installed.

Blocks return a body carrying the trace id, the decision id, the rule that fired and
a human-readable reason. Never block without an auditable reason (X-4).

**Two verdicts, and which one to gate on.** Every enforcement body and every set of
response headers here carries both:

* ``verdict`` / ``applied_verdict`` (``X-Nometria-Verdict``,
  ``X-Nometria-Applied-Verdict``) — what actually happened to this request.
* ``effective_verdict`` / ``would_be_verdict`` (``X-Nometria-Effective-Verdict``,
  ``X-Nometria-Would-Be-Verdict``) — the counterfactual: what the bound policy asserts
  should happen. In observe mode this is the verdict that did *not* take effect.

Gate on the applied one. Gating on the counterfactual means refusing traffic this
platform allowed, which is the opposite of what observe mode is for. The
``applied_``/``would_be_`` names are aliases added by ``gateway/verdicts.py``; the
original keys are unchanged and carry the same values.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.gateway.deps import agent_credential, db, ingest_credential
from agentfox.gateway.verdicts import verdict_headers, with_verdict_aliases
from agentfox.prove.audit.otel import ingest_otlp
from agentfox.registry.service import detect_shadow_agents
from agentfox.runtime.agent_loop import LoopBudget, Step, govern_loop
from agentfox.runtime.enforcement import EnforcementResult, Enforcer

log = logging.getLogger(__name__)

router = APIRouter(tags=["inline"])


def _record_turn(
    session: Session,
    *,
    agent_slug: str | None,
    session_id: str | None,
    trace_id: str | None,
    messages: list[dict[str, Any]],
    answer: str,
) -> None:
    """P11 over HTTP — the same gap the SDK path had for entitlement: escalation
    governance reads recorded conversation turns, and only the SDK's `agentfox.auto()`
    monkeypatch was ever recording them (autoguard.py's `_record_turn`). A team
    integrating via this HTTP gateway directly — not the Python SDK — got zero
    escalation tracking, however long they ran it. Never breaks the caller's request.
    """
    if not answer or not trace_id:
        return
    try:
        from agentfox.containment.escalation import record_turn
        from agentfox.core.models import Agent

        user_text = next(
            (
                str(m.get("content") or "")
                for m in reversed(messages)
                if str(m.get("role")) == "user"
            ),
            "",
        )
        if not user_text:
            return
        agent = (
            session.scalar(select(Agent).where(Agent.slug == agent_slug)) if agent_slug else None
        )
        record_turn(
            session,
            session_id=session_id or trace_id,
            agent_id=agent.id if agent else None,
            trace_id=trace_id,
            user_text=user_text,
            agent_text=answer,
        )
    except Exception:  # pragma: no cover - observability must not break the call
        pass


def _trust_map(header: str | None) -> dict[str, str] | None:
    if not header:
        return None
    try:
        return {str(k): str(v) for k, v in json.loads(header).items()}
    except Exception:
        return None


def _evidence_from_body(session: Session, body: dict[str, Any]) -> dict[str, Any] | None:
    """P10 over HTTP — the caller declares who's asking and what was retrieved.

    Without this, ``run_completion``'s ``evidence=`` kwarg (which entitlement
    checking reads) is never populated by ordinary gateway traffic, so a real
    integrator has no way to make disclosure checks run short of calling
    ``/api/entitlement/filter`` directly and separately. ``principal`` and
    ``retrieved`` are optional body fields; either one is enough to build evidence
    — a subject with no registered principal still records correctly as
    "declared but unregistered" downstream (see entitlement.filter_retrieval).
    """
    principal_ref = body.get("principal")
    chunks = body.get("retrieved") or body.get("chunks")
    if principal_ref is None and not chunks:
        return None
    from agentfox.core.models import EndUserPrincipal

    principal = None
    if principal_ref is not None:
        subject = (
            principal_ref.get("subject") if isinstance(principal_ref, dict) else str(principal_ref)
        )
        principal = session.scalar(
            select(EndUserPrincipal).where(EndUserPrincipal.subject == subject)
        )
    return {"principal": principal, "chunks": chunks or [], "purpose": body.get("purpose")}


def _explain_url(result) -> str:
    """Where a person can go to read this decision, or "" when nobody has said.

    The single cheapest thing this response can do for the engineer who receives
    it. They meet a block as a line in a log, holding a decision id and a trace id,
    and until now had to know that a dashboard exists, that it has a Traces page,
    and how to get from an opaque identifier to the right row on it. Most of them
    will instead file a ticket saying the gateway is broken.

    Built only from `console_url`, which an operator sets explicitly. Deriving it
    from the request's Host header would be guessing: behind a proxy that is
    whatever the proxy sent, and a link to somewhere that does not exist is worse
    than no link at all.
    """
    from agentfox.core.config import get_settings

    base = (getattr(get_settings(), "console_url", "") or "").rstrip("/")
    trace_id = getattr(result, "trace_id", None)
    if not base or not trace_id:
        return ""
    return f"{base}/app/traces/{trace_id}"


def _blocked_response(result, status: int = 403) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "type": "agentfox_policy_violation",
                "message": result.reason or "blocked by policy",
                # Both names, same values: `applied_verdict`/`would_be_verdict` say
                # which one took effect (gateway/verdicts.py).
                "verdict": result.verdict,
                "applied_verdict": result.verdict,
                "effective_verdict": result.effective_verdict,
                "would_be_verdict": result.effective_verdict,
                "trace_id": result.trace_id,
                "decision_id": result.decision_id,
                "policy_version": result.policy_version_id,
                "rules_fired": result.rules_fired,
                "entities": result.entities,
                "approval_id": result.approval_id,
                # P3-12: "blocked by policy" is not an explanation, and an engineer
                # who cannot tell whether the guardrail was right will disable it.
                # The cheapest fix for a false positive must be filing one, not
                # turning the detector off — so the dispute route ships in the error.
                "explanation": result.explanation,
                "suppressed": result.suppressed,
                # Omitted rather than empty when `console_url` is unset: a null link
                # in a response is a thing to handle, an absent key is not.
                **({"explain_url": url} if (url := _explain_url(result)) else {}),
            }
        },
        headers=_headers(result),
    )


def _headers(result) -> dict[str, str]:
    """Governance headers, with both namings of the two verdicts.

    `X-Nometria-Verdict` and `X-Nometria-Effective-Verdict` keep exactly the values
    they had. `X-Nometria-Applied-Verdict` and `X-Nometria-Would-Be-Verdict` repeat
    them under names that say which one took effect.
    """
    return {
        "X-Nometria-Trace": result.trace_id or "",
        "X-Nometria-Verdict": result.verdict,
        "X-Nometria-Effective-Verdict": result.effective_verdict,
        **verdict_headers(result),
        "X-Nometria-Decision": result.decision_id or "",
        "X-Nometria-Mode": result.mode,
        "X-Nometria-Latency-Ms": f"{result.latency_ms:.2f}",
        # In the headers too, because the response body of a streamed completion is
        # a sequence of SSE frames and the engineer debugging one is reading curl -i.
        **({"X-Nometria-Explain": url} if (url := _explain_url(result)) else {}),
    }


# ---------------------------------------------------------------------------
# Loop governance across the proxy's tool loop (gap 0.4)
# ---------------------------------------------------------------------------
#
# `agent_loop.py` was already called from `enforcement.py::_budget_state`, but only to
# score the *one* decision in front of it: a caller had to thread its own step history
# in through `/v1/guard/tool_call`'s `prior_steps`. The drop-in proxy — the surface
# this product's whole X-1 pitch is built on — forwarded `tools` and `tool_calls`
# straight through and governed nothing across turns. An agent alternating A-B-A-B
# forever through `/v1/chat/completions` was invisible, because every individual
# request looked perfectly reasonable.
#
# Nothing extra is needed from the client to fix that: both proxied protocols carry
# the entire prior loop in the request body, because that is how a tool-calling client
# works. The run can therefore be reconstructed from the body alone — no server-side
# per-session state to go stale, to be lost when this stateless process is replaced
# (NFR-3), or to leak between tenants.


def _tool_steps(messages: list[dict[str, Any]]) -> list[Step]:
    """Rebuild the tool-calling run from the conversation the client sent.

    Handles both wire shapes: OpenAI's `assistant.tool_calls` answered by a
    `role="tool"` message keyed on `tool_call_id`, and Anthropic's `tool_use` content
    blocks answered by `tool_result` blocks keyed on `tool_use_id`. Anything that is
    not a recognisable tool call is ignored rather than guessed at — a malformed body
    must not manufacture a loop that is not there.
    """
    calls: list[tuple[str, str, dict[str, Any]]] = []
    observations: dict[str, Any] = {}

    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")

        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            raw = function.get("arguments", call.get("arguments"))
            if isinstance(raw, str):
                try:
                    arguments = json.loads(raw)
                except Exception:
                    # Unparseable arguments still identify the call; keeping the raw
                    # string means two identical bad calls still fingerprint alike.
                    arguments = {"_raw": raw}
            else:
                arguments = raw
            calls.append(
                (
                    str(call.get("id") or f"call_{len(calls)}"),
                    str(function.get("name") or call.get("name") or ""),
                    arguments if isinstance(arguments, dict) else {"_value": arguments},
                )
            )

        if str(message.get("role") or "") == "tool" and message.get("tool_call_id"):
            observations[str(message["tool_call_id"])] = content

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    payload = block.get("input")
                    calls.append(
                        (
                            str(block.get("id") or f"call_{len(calls)}"),
                            str(block.get("name") or ""),
                            payload if isinstance(payload, dict) else {"_value": payload},
                        )
                    )
                elif block.get("type") == "tool_result" and block.get("tool_use_id"):
                    observations[str(block["tool_use_id"])] = block.get("content")

    return [
        Step(tool=tool, arguments=arguments, observation=observations.get(call_id))
        for call_id, tool, arguments in calls
        if tool
    ]


def _loop_budget() -> LoopBudget:
    """The deployment's declared `AGENTFOX_LOOP_*` budgets — the same ones
    `enforcement.py::_budget_state` reads, so the proxy and the direct guard endpoint
    cannot disagree about what a runaway loop is."""
    settings = get_settings()
    return LoopBudget(
        max_steps=settings.loop_max_steps,
        max_repeats=settings.loop_max_repeats,
        max_cycle_length=settings.loop_max_cycle_length,
        max_steps_without_progress=settings.loop_max_steps_without_progress,
    )


def _record_loop_stop(
    session: Session, *, agent_slug: str | None, session_id: str, verdict, steps: list[Step]
) -> str | None:
    """Trace the refusal and raise a finding. Returns the trace id, or None.

    Never raises: a refusal that fails to record is still a correct refusal, and
    turning it into a 500 would replace a governed stop with an outage.
    """
    trace_id = None
    try:
        from agentfox.core.models import Agent
        from agentfox.prove.audit.trace import start_trace
        from agentfox.prove.findings import raise_finding

        agent = (
            session.scalar(select(Agent).where(Agent.slug == agent_slug)) if agent_slug else None
        )
        trace = start_trace(
            session,
            agent_id=agent.id if agent else None,
            agent_slug=agent_slug,
            session_id=session_id,
        )
        trace_id = trace.id
        # One finding per (agent, session): a loop that keeps being stopped in the same
        # session is one runaway with a count, not a row per refused step.
        raise_finding(
            session,
            type="agent_loop_stopped",
            severity="medium",
            title=f"Runaway tool loop stopped for '{agent_slug or 'unregistered agent'}'"[:300],
            subject_type="agent",
            subject_id=(agent_slug or session_id)[:120],
            fingerprint_parts=(session_id,),
            evidence={
                "decision": verdict.decision,
                "reason": verdict.reason,
                "step": verdict.step,
                "evidence": verdict.evidence,
                "session_id": session_id,
                "steps_seen": len(steps),
                "tools": [s.tool for s in steps],
                "trace_id": trace_id,
            },
            control_keys=["NOM-RTG-08"],
        )
        session.flush()
    except Exception:  # pragma: no cover - recording must not break the refusal
        log.warning("could not record a stopped agent loop", exc_info=True)
    return trace_id


def _govern_tool_loop(
    session: Session,
    *,
    agent_slug: str | None,
    session_id: str | None,
    messages: list[dict[str, Any]],
) -> JSONResponse | None:
    """A refusal when the client's tool loop has stopped getting anywhere, else None.

    Gated on the session header the route already reads. Without one there is no
    correlation key to attribute the run to, and guessing would mean one tenant's
    traffic could stop another's — so a client that supplies no session is left
    exactly as it was. Same for a request carrying no tool calls at all: the
    overwhelmingly common single-turn chat request must be untouched by this.
    """
    if not session_id:
        return None
    try:
        steps = _tool_steps(messages)
        if not steps:
            return None
        verdict = govern_loop(steps, budget=_loop_budget())
        if not verdict.stopped:
            return None
    except Exception:  # pragma: no cover - loop scoring must not break the call
        log.warning("loop governance failed; request proceeds", exc_info=True)
        return None

    trace_id = _record_loop_stop(
        session, agent_slug=agent_slug, session_id=session_id, verdict=verdict, steps=steps
    )
    budget = _loop_budget()
    result = EnforcementResult(
        verdict="block",
        effective_verdict="block",
        mode="enforce",
        trace_id=trace_id,
        reason=verdict.reason,
        # `loop.runaway` is the rule id the shipped tool-containment policy already
        # uses for exactly this condition (controls NOM-RTG-08), so an operator reading
        # a proxy refusal and one from `/v1/guard/tool_call` sees one vocabulary.
        rules_fired=[
            {
                "rule_id": "loop.runaway",
                "effect": "block",
                "reason": verdict.reason,
                "severity": "medium",
                "controls": ["NOM-RTG-08"],
                "evidence": {
                    "decision": verdict.decision,
                    "step": verdict.step,
                    **verdict.evidence,
                },
            }
        ],
        explanation={
            "control": "agent loop governance (PL-4, gap 0.4)",
            "decision": verdict.decision,
            "stopped_at_step": verdict.step,
            "steps_seen": len(steps),
            "tools": [s.tool for s in steps],
            "session_id": session_id,
            "budget": {
                "max_steps": budget.max_steps,
                "max_repeats": budget.max_repeats,
                "max_cycle_length": budget.max_cycle_length,
                "max_steps_without_progress": budget.max_steps_without_progress,
            },
        },
    )
    return _blocked_response(result)


# ---------------------------------------------------------------------------
# SSE rendering (PL-1)
# ---------------------------------------------------------------------------


def _sse(payload: Any) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _openai_chunk(
    model: str, delta: str = "", finish: str | None = None, chunk_id: str = ""
) -> dict[str, Any]:
    return {
        "id": chunk_id or "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta} if delta else {},
                "finish_reason": finish,
            }
        ],
    }


def _stream_openai(events, model: str):
    """Render enforced stream events as an OpenAI-compatible SSE stream.

    A block mid-stream emits an `error` event and then `[DONE]`, so a client that
    follows the OpenAI protocol terminates cleanly and *knows why* — rather than the
    silent truncation that a bare connection close would produce.
    """
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    for event in events:
        if event.kind == "delta":
            yield _sse(_openai_chunk(model, delta=event.delta, chunk_id=chunk_id))
        elif event.kind == "blocked":
            result = event.result
            yield _sse(
                {
                    "error": {
                        "type": "agentfox_policy_violation",
                        "message": result.reason or "blocked by policy",
                        "verdict": result.verdict,
                        "applied_verdict": result.verdict,
                        "would_be_verdict": result.effective_verdict,
                        "trace_id": result.trace_id,
                        "decision_id": result.decision_id,
                        "rules_fired": result.rules_fired,
                        "entities": result.entities,
                    }
                }
            )
            yield "data: [DONE]\n\n"
            return
        elif event.kind == "done":
            yield _sse(
                _openai_chunk(model, finish=event.finish_reason or "stop", chunk_id=chunk_id)
            )
            # Trailing governance metadata: verdict is only knowable at the end, and
            # headers were already flushed when the stream opened.
            yield _sse(
                {"agentfox": with_verdict_aliases(event.result.to_json()) if event.result else {}}
            )
            yield "data: [DONE]\n\n"
            return
    yield "data: [DONE]\n\n"


def _stream_anthropic(events, model: str):
    """Render as Anthropic message-stream events."""
    yield _sse(
        {
            "type": "message_start",
            "message": {
                "id": f"msg_{uuid.uuid4().hex[:12]}",
                "model": model,
                "role": "assistant",
                "content": [],
            },
        }
    )
    yield _sse(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    )
    for event in events:
        if event.kind == "delta":
            yield _sse(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": event.delta},
                }
            )
        elif event.kind == "blocked":
            result = event.result
            yield _sse(
                {
                    "type": "error",
                    "error": {
                        "type": "agentfox_policy_violation",
                        "message": result.reason or "blocked by policy",
                        "trace_id": result.trace_id,
                        "rules_fired": result.rules_fired,
                    },
                }
            )
            return
        elif event.kind == "done":
            yield _sse({"type": "content_block_stop", "index": 0})
            yield _sse(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": event.finish_reason or "end_turn"},
                    "usage": event.usage,
                    "agentfox": with_verdict_aliases(event.result.to_json())
                    if event.result
                    else {},
                }
            )
            yield _sse({"type": "message_stop"})
            return


def _stream_headers(trace_hint: str = "") -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Nometria-Streaming": "enforced",
        "X-Nometria-Trace": trace_hint,
    }


@router.post("/v1/chat/completions", summary="OpenAI-compatible inline proxy")
async def chat_completions(
    request: Request,
    session: Session = Depends(db),
    credential: str | None = Depends(agent_credential),
    x_nometria_agent: Annotated[str | None, Header()] = None,
    x_nometria_session: Annotated[str | None, Header()] = None,
    x_nometria_environment: Annotated[str | None, Header()] = None,
    x_nometria_intent: Annotated[str | None, Header()] = None,
    x_nometria_trust: Annotated[str | None, Header()] = None,
    x_nometria_provider: Annotated[str | None, Header()] = None,
    x_nometria_stream_mode: Annotated[str | None, Header()] = None,
) -> Any:
    body = await request.json()
    enforcer = Enforcer(session)
    evidence = _evidence_from_body(session, body)

    # Ahead of the stream branch so a streaming client is governed identically — a
    # runaway loop that escapes by setting `"stream": true` is not governed.
    refusal = _govern_tool_loop(
        session,
        agent_slug=x_nometria_agent,
        session_id=x_nometria_session,
        messages=body.get("messages", []),
    )
    if refusal is not None:
        return refusal

    if body.get("stream"):
        # PL-1: honour the caller's protocol. Previously this flag was silently
        # ignored and a non-streaming body returned, which breaks every streaming
        # client without telling it anything.
        events = enforcer.run_completion_stream(
            agent_slug=x_nometria_agent,
            messages=body.get("messages", []),
            model=body.get("model", "default"),
            provider=x_nometria_provider,
            credential=credential,
            environment=x_nometria_environment or "production",
            session_id=x_nometria_session,
            intent=x_nometria_intent,
            trust_map=_trust_map(x_nometria_trust),
            correlation=dict(request.headers),
            temperature=float(body.get("temperature", 0.0)),
            max_tokens=body.get("max_tokens"),
            mode=x_nometria_stream_mode,
            evidence=evidence,
        )
        return StreamingResponse(
            _stream_openai(events, body.get("model", "")),
            media_type="text/event-stream",
            headers=_stream_headers(),
        )

    result, response = enforcer.run_completion(
        agent_slug=x_nometria_agent,
        messages=body.get("messages", []),
        model=body.get("model", "default"),
        provider=x_nometria_provider,
        credential=credential,
        environment=x_nometria_environment or "production",
        session_id=x_nometria_session,
        intent=x_nometria_intent,
        trust_map=_trust_map(x_nometria_trust),
        correlation=dict(request.headers),
        temperature=float(body.get("temperature", 0.0)),
        max_tokens=body.get("max_tokens"),
        evidence=evidence,
    )
    if result.blocked:
        return _blocked_response(result)
    if result.escalated:
        return JSONResponse(
            status_code=202,
            content={
                "status": "awaiting_approval",
                "approval_id": result.approval_id,
                "poll": f"/api/approvals/{result.approval_id}",
                "reason": result.reason,
                "trace_id": result.trace_id,
            },
            headers=_headers(result),
        )
    _record_turn(
        session,
        agent_slug=x_nometria_agent,
        session_id=x_nometria_session,
        trace_id=result.trace_id,
        messages=body.get("messages", []),
        answer=response.text,
    )
    return JSONResponse(content=response.to_openai(body.get("model", "")), headers=_headers(result))


@router.post("/v1/messages", summary="Anthropic-compatible inline proxy")
async def messages(
    request: Request,
    session: Session = Depends(db),
    credential: str | None = Depends(agent_credential),
    x_nometria_agent: Annotated[str | None, Header()] = None,
    x_nometria_session: Annotated[str | None, Header()] = None,
    x_nometria_environment: Annotated[str | None, Header()] = None,
    x_nometria_intent: Annotated[str | None, Header()] = None,
    x_nometria_trust: Annotated[str | None, Header()] = None,
    x_nometria_provider: Annotated[str | None, Header()] = None,
    x_nometria_stream_mode: Annotated[str | None, Header()] = None,
) -> Any:
    body = await request.json()
    payload = list(body.get("messages", []))
    if body.get("system"):
        payload = [{"role": "system", "content": body["system"]}, *payload]

    enforcer = Enforcer(session)
    evidence = _evidence_from_body(session, body)

    refusal = _govern_tool_loop(
        session,
        agent_slug=x_nometria_agent,
        session_id=x_nometria_session,
        messages=payload,
    )
    if refusal is not None:
        return refusal

    if body.get("stream"):
        events = enforcer.run_completion_stream(
            agent_slug=x_nometria_agent,
            messages=payload,
            model=body.get("model", "default"),
            provider=x_nometria_provider,
            credential=credential,
            environment=x_nometria_environment or "production",
            session_id=x_nometria_session,
            intent=x_nometria_intent,
            trust_map=_trust_map(x_nometria_trust),
            correlation=dict(request.headers),
            temperature=float(body.get("temperature", 0.0)),
            max_tokens=body.get("max_tokens"),
            mode=x_nometria_stream_mode,
            evidence=evidence,
        )
        return StreamingResponse(
            _stream_anthropic(events, body.get("model", "")),
            media_type="text/event-stream",
            headers=_stream_headers(),
        )

    result, response = enforcer.run_completion(
        agent_slug=x_nometria_agent,
        messages=payload,
        model=body.get("model", "default"),
        provider=x_nometria_provider,
        credential=credential,
        environment=x_nometria_environment or "production",
        session_id=x_nometria_session,
        intent=x_nometria_intent,
        trust_map=_trust_map(x_nometria_trust),
        correlation=dict(request.headers),
        temperature=float(body.get("temperature", 0.0)),
        max_tokens=body.get("max_tokens"),
        evidence=evidence,
    )
    if result.blocked:
        return _blocked_response(result)
    if result.escalated:
        return JSONResponse(
            status_code=202,
            content={
                "status": "awaiting_approval",
                "approval_id": result.approval_id,
                "reason": result.reason,
                "trace_id": result.trace_id,
            },
            headers=_headers(result),
        )
    _record_turn(
        session,
        agent_slug=x_nometria_agent,
        session_id=x_nometria_session,
        trace_id=result.trace_id,
        messages=payload,
        answer=response.text,
    )
    return JSONResponse(
        content=response.to_anthropic(body.get("model", "")), headers=_headers(result)
    )


# ---------------------------------------------------------------------------
# Direct guard endpoints — for teams that keep their own provider calls
# ---------------------------------------------------------------------------


class McpCallRequest(BaseModel):
    server: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)
    # The gateway cannot dial an arbitrary MCP server on the caller's behalf without
    # becoming an SSRF surface, so the caller supplies the result it got and we govern
    # both edges of it. Enforcement is inline either way; only the transport moves.
    result: Any = None


@router.post("/v1/mcp/call", summary="Govern an MCP tool call (I-2)")
def mcp_call(
    payload: McpCallRequest,
    session: Session = Depends(db),
    credential: str | None = Depends(agent_credential),
    x_nometria_agent: Annotated[str | None, Header()] = None,
    x_nometria_intent: Annotated[str | None, Header()] = None,
) -> Any:
    """Govern one MCP call for callers that are not in-process Python.

    Pre-call the arguments are authorised against the tool's capability and taint
    ceiling; post-call the result is evaluated on the ``tool_result`` surface and
    returned redacted where policy says so.
    """
    from agentfox.integrations.mcp import McpGovernor

    governor = McpGovernor(
        session=session,
        agent_slug=x_nometria_agent or "",
        server_name=payload.server,
        credential=credential,
        intent=x_nometria_intent,
    )
    outcome = governor.call(
        payload.tool,
        payload.arguments,
        provenance=payload.provenance or None,
        transport=lambda _t, _a: payload.result,
    )
    decision = outcome.post_decision or outcome.pre_decision
    if not outcome.allowed and decision is not None:
        return _blocked_response(decision)
    return JSONResponse(
        content={"result": outcome.result, **with_verdict_aliases(outcome.to_json())}
    )


class GuardContentRequest(BaseModel):
    agent: str
    content: str
    surface: str = "input"
    taint_source: str = "user"
    intent: str | None = None
    # Accepted so a caller guarding an input and then its output can tie the two
    # together into one trace instead of two unrelated ones. Optional, because the
    # commonest integration is a single call in a middleware that has no id to give.
    session_id: str | None = None
    trace_id: str | None = None


class GuardToolCallRequest(BaseModel):
    agent: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)
    intent: str | None = None
    prior_tools: list[str] = Field(default_factory=list)
    # PL-4 — a caller that already tracks its own step history (tool, arguments,
    # observation) can pass it so the real LoopGovernor sees alternating cycles and
    # stalled runs, not just a per-tool repeat count. Must default to None, not [] —
    # _budget_state() branches on `prior_steps is not None`, so an empty list from a
    # caller that never heard of this field would silently disable the old
    # repeats>=3 fallback instead of falling through to it.
    prior_steps: list[dict[str, Any]] | None = None
    session_id: str | None = None


@router.post("/v1/guard/input", summary="Enforce on an input without proxying")
@router.post("/v1/guard/output", summary="Enforce on an output without proxying")
def guard_content(
    payload: GuardContentRequest,
    request: Request,
    session: Session = Depends(db),
) -> dict[str, Any]:
    """Enforce on content without proxying.

    The route's first line is kept short because `scripts/api_routes.py` uses it as
    this operation's label in Appendix C.

    `verdict`/`applied_verdict` is what happened; `effective_verdict`/
    `would_be_verdict` is what the bound policy says should happen, which in observe
    mode is the one that did not take effect. Gate on the applied one.
    """
    from agentfox.core.config import get_settings
    from agentfox.core.models import Trace
    from agentfox.prove.audit.trace import end_trace, start_trace
    from agentfox.registry.service import slugify

    surface = "output" if request.url.path.endswith("/output") else payload.surface

    # A governed request is a trace of one step, and recording it as one is what
    # makes this integration visible.
    #
    # The three other guard routes — tool_call, memory_write, agent_message — have
    # always called `start_trace`. This one, the most used of the four, did not, and
    # the consequence was out of all proportion to the omission: `Trace` is what the
    # Traces page lists, what `/api/onboarding` reads to decide whether anything is
    # connected at all, what gives an agent a last-seen, and what the control
    # telemetry computes effectiveness from. So a team integrating through
    # `/v1/guard/input` — the lower-friction path, and the one picked by anyone
    # unwilling to route every model call through a new proxy — could govern
    # thousands of requests and still be told "Nothing is sending traffic yet", with
    # the findings from those very requests counted in the header above the message.
    #
    # Same class of bug as the one `_record_turn` at the top of this module exists to
    # fix: a capability wired to the SDK path only, and silently absent for everyone
    # on the HTTP one.
    enforcer = Enforcer(session)
    # Resolve before starting the trace so the trace carries an agent id, which is
    # what gives the agent a last-seen and lets the Traces page filter by agent.
    # `resolve` also registers an unknown slug as shadow traffic, which is the
    # behaviour this path is documented to have (P1-6) and did not reach from here.
    agent, _identity, _shadow = enforcer.resolve(payload.agent)
    # Reuse rather than insert when the caller names a trace that already exists:
    # guarding the input and then the output is two calls about one request, and the
    # whole point of accepting `trace_id` is to let a caller say so. `start_trace`
    # always inserts, so passing a known id straight through turned the second call
    # into a 500 on a primary-key collision — the integration would have worked right
    # up until the moment somebody used the field as documented.
    trace = session.get(Trace, payload.trace_id) if payload.trace_id else None
    if trace is None:
        trace = start_trace(
            session,
            agent_id=agent.id if agent else None,
            agent_slug=slugify(payload.agent),
            session_id=payload.session_id,
            intent=payload.intent,
            trace_id=payload.trace_id,
        )
    result = enforcer.check_content(
        agent_slug=payload.agent,
        content=payload.content,
        surface=surface,
        taint_source=payload.taint_source,
        trace=trace,
    )
    # `evaluate` raises the trace's verdict to the strongest thing that happened on
    # it, so ending it must not overwrite that with the default: a second guard call
    # on the same trace_id that allows must not erase the first one that blocked.
    end_trace(session, trace, verdict=trace.verdict, status=trace.status)
    # On this route too, and on every verdict rather than only the blocking ones:
    # the commonest question about an *allowed* request is "why did you flag it and
    # let it through", which is the same page.
    console = (getattr(get_settings(), "console_url", "") or "").rstrip("/")
    if console:
        result["explain_url"] = f"{console}/app/traces/{trace.id}"
    return with_verdict_aliases(result)


@router.post("/v1/guard/tool_call", summary="Authorise a tool call (P3-4, P2-2)")
def guard_tool_call(
    payload: GuardToolCallRequest,
    session: Session = Depends(db),
    credential: str | None = Depends(agent_credential),
) -> dict[str, Any]:
    from agentfox.prove.audit.trace import start_trace
    from agentfox.registry.service import slugify

    enforcer = Enforcer(session)
    agent, _identity, _shadow = enforcer.resolve(payload.agent, credential)
    trace = start_trace(
        session,
        agent_id=agent.id if agent else None,
        agent_slug=slugify(payload.agent),
        session_id=payload.session_id,
        intent=payload.intent,
    )
    result = enforcer.guard_tool_call(
        agent_slug=payload.agent,
        tool_key=payload.tool,
        arguments=payload.arguments,
        provenance=payload.provenance,
        intent=payload.intent,
        trace=trace,
        credential=credential,
        prior_tools=payload.prior_tools,
        prior_steps=payload.prior_steps,
    )
    return with_verdict_aliases(result.to_json())


class GuardMemoryWriteRequest(BaseModel):
    agent: str
    content: str
    subject: str | None = None
    taint_source: str = "user"
    provenance: dict[str, Any] = Field(default_factory=dict)
    verified_by: str | None = None
    ttl_seconds: int | None = None
    session_id: str | None = None


@router.post("/v1/guard/memory_write", summary="Authorise a memory write (P14, NOM-RTG-13)")
def guard_memory_write(
    payload: GuardMemoryWriteRequest,
    session: Session = Depends(db),
    credential: str | None = Depends(agent_credential),
) -> dict[str, Any]:
    from agentfox.prove.audit.trace import start_trace
    from agentfox.registry.service import slugify

    enforcer = Enforcer(session)
    agent, _identity, _shadow = enforcer.resolve(payload.agent, credential)
    trace = start_trace(
        session,
        agent_id=agent.id if agent else None,
        agent_slug=slugify(payload.agent),
        session_id=payload.session_id,
    )
    result = enforcer.guard_memory_write(
        agent_slug=payload.agent,
        content=payload.content,
        subject=payload.subject,
        taint_source=payload.taint_source,
        provenance=payload.provenance,
        verified_by=payload.verified_by,
        ttl_seconds=payload.ttl_seconds,
        trace=trace,
        credential=credential,
    )
    return with_verdict_aliases(result.to_json())


class GuardAgentMessageRequest(BaseModel):
    sender: str
    content: str
    recipient: str | None = None
    nonce: str | None = None
    timestamp: float | None = None
    signature: str | None = None
    session_id: str | None = None


@router.post(
    "/v1/guard/agent_message", summary="Authorise an inter-agent message (P17, NOM-IAM-08)"
)
def guard_agent_message(
    payload: GuardAgentMessageRequest,
    session: Session = Depends(db),
    credential: str | None = Depends(agent_credential),
) -> dict[str, Any]:
    from agentfox.prove.audit.trace import start_trace
    from agentfox.registry.service import slugify

    enforcer = Enforcer(session)
    agent, _identity, _shadow = enforcer.resolve(payload.sender, credential)
    trace = start_trace(
        session,
        agent_id=agent.id if agent else None,
        agent_slug=slugify(payload.sender),
        session_id=payload.session_id,
    )
    result = enforcer.guard_agent_message(
        sender_slug=payload.sender,
        content=payload.content,
        recipient_slug=payload.recipient,
        nonce=payload.nonce,
        timestamp=payload.timestamp,
        signature=payload.signature,
        trace=trace,
    )
    return with_verdict_aliases(result.to_json())


# ---------------------------------------------------------------------------
# OTLP ingest (X-1c) — the zero-integration surface
# ---------------------------------------------------------------------------


@router.post("/v1/traces", summary="OTLP/HTTP trace ingest")
async def ingest_traces(
    request: Request,
    session: Session = Depends(db),
    _credential: str | None = Depends(ingest_credential),
) -> dict[str, Any]:
    payload = await request.json()
    summary = ingest_otlp(session, payload)

    # Passive observation is enough to populate the registry and raise shadow-agent
    # findings — a team gets Pillars 1 and 5 without changing a line of code.
    from agentfox.registry.service import observe_agent

    for slug in summary.get("agents_seen", []):
        observe_agent(
            session,
            slug,
            framework=summary.get("frameworks", {}).get(slug),
        )
    summary["shadow_agents"] = detect_shadow_agents(session)
    return summary
