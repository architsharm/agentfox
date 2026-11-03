"""Tool calls from hosted agent platforms, governed before they run.

Vapi, Retell and Copilot Studio each call a URL of the customer's choosing before an
agent's tool runs. Pointed here, that call is translated into ``POST
/v1/guard/tool_call``'s decision for the agent the
:class:`~agentfox.core.models.PlatformConnection` names, and answered in the
platform's own format:

* **Vapi** (``/v1/hooks/vapi/{id}``, the tool's server URL): each call in
  ``toolCallList`` is decided; a blocked or held one is answered with an ``error`` the
  assistant speaks, the allowed ones are forwarded to the customer's tool server and
  its ``results`` returned.
* **Retell** (``/v1/hooks/retell/{id}``, the custom function's URL): the function call
  is decided after its ``X-Retell-Signature`` is verified; a refusal is a sentence
  the agent says, an allowed call is forwarded.
* **Copilot Studio** (``/v1/hooks/copilot-studio/{id}``, the external threat
  detection endpoint): ``/analyze-tool-execution`` answers ``blockAction`` and
  ``/validate`` the health check, after the Entra token is verified.

A refusal never says why in terms a caller could use to rephrase around the rule: it
says the action was not done and, when a person has to approve it, that it was sent
for approval. The full reasoning is on the trace, as for every other guard route.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import activate_posture, db, require
from agentfox.apps.gateway.routes.inline import GuardToolCallRequest, authorise_tool_call
from agentfox.core.crypto import EncryptionNotConfigured
from agentfox.core.models import Agent, PlatformConnection, User
from agentfox.core.tenancy import bind_session
from agentfox.platform.ledger import chain
from agentfox.platform.registry import platform_connections as connections
from agentfox.runtime.enforcement.result import STOPPING_VERDICTS

log = logging.getLogger(__name__)

router = APIRouter(tags=["platform hooks"])
admin_router = APIRouter(prefix="/api", tags=["registry"])

#: The most a platform's delivery may be.
MAX_HOOK_BYTES = 512_000


async def _raw_body(request: Request) -> bytes:
    body = await request.body()
    if len(body) > MAX_HOOK_BYTES:
        raise HTTPException(413, "payload too large")
    return body


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body or b"{}")
    except ValueError as exc:
        raise HTTPException(400, "body is not JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "body is not a JSON object")
    return data


def _obj(value: Any) -> dict[str, Any]:
    """``value`` when it is a JSON object, else an empty one: platforms omit fields."""
    return value if isinstance(value, dict) else {}


def _connection(session: Session, connection_id: str, platform: str) -> PlatformConnection:
    """The connection the URL names, with the session bound to its tenant. Unknown and
    disabled connections are the same 404, so a guessed id learns nothing."""
    connection = connections.find(session, connection_id, platform)
    if connection is None:
        raise HTTPException(404, "unknown connection")
    bind_session(session, connection.org_id)
    activate_posture(session)
    return connection


def _agent_slug(session: Session, connection: PlatformConnection) -> str:
    agent = session.get(Agent, connection.agent_id)
    if agent is None:
        raise HTTPException(404, "unknown connection")
    return agent.slug


def _arguments(raw: Any) -> dict[str, Any]:
    """A tool call's arguments: platforms send an object or a JSON string of one."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            return {"_raw": raw}
    return raw if isinstance(raw, dict) else {}


def _decide(
    session: Session,
    agent: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    session_id: str | None,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = GuardToolCallRequest(
        agent=agent,
        tool=tool,
        arguments=arguments,
        messages=messages or None,
        session_id=session_id,
        # The platforms never send an approval id back: a retry of a call a person
        # has since approved is matched by agent, tool and arguments instead.
        redeem_approved=True,
    )
    return authorise_tool_call(session, payload, credential=None)


def _stopped(result: dict[str, Any]) -> bool:
    # The policy's own verdict, as every SDK adapter reads it: a rule in observe mode
    # reports what it would have done without stopping anything.
    return str(result.get("verdict")) in STOPPING_VERDICTS


def refusal(result: dict[str, Any]) -> str:
    """What the agent says when a call was not run. Plain, and the same shape for
    every rule, so a caller learns nothing to rephrase around."""
    if result.get("verdict") == "escalate" and result.get("approval_id"):
        return (
            "This action was not done: it needs a person to approve it, and it has been "
            "sent for approval. Tell the caller it is pending; once a person approves it, "
            "the same request will go through when they ask again."
        )
    return (
        "This action was not done: it is not allowed by this organisation's policy. Tell "
        "the caller you can't do that for them, and offer another way to help."
    )


# ---------------------------------------------------------------------------
# Vapi
# ---------------------------------------------------------------------------


def _vapi_authorised(
    connection: PlatformConnection, authorization: str | None, x_vapi_secret: str | None
) -> bool:
    secret = connections.secret_of(connection)
    if not secret:
        return False
    presented = x_vapi_secret or ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization.split(" ", 1)[1].strip()
    return bool(presented) and hmac.compare_digest(presented, secret)


@router.post("/v1/hooks/vapi/{connection_id}", summary="Govern a Vapi assistant's tool calls")
def vapi_hook(
    connection_id: str,
    body: bytes = Depends(_raw_body),
    session: Session = Depends(db),
    authorization: Annotated[str | None, Header()] = None,
    x_vapi_secret: Annotated[str | None, Header()] = None,
) -> Response:
    """Vapi's server URL for a tool (or the assistant): ``tool-calls`` messages are
    governed call by call, everything else Vapi sends is acknowledged and ignored.

    Authenticated by the connection's secret, sent by a Vapi Bearer credential (or the
    legacy ``X-Vapi-Secret`` header)."""
    connection = _connection(session, connection_id, "vapi")
    if not _vapi_authorised(connection, authorization, x_vapi_secret):
        raise HTTPException(401, "the connection's secret was not presented")
    event = _json_object(body)
    message = _obj(event.get("message"))
    if message.get("type") != "tool-calls":
        return JSONResponse({})
    agent = _agent_slug(session, connection)
    call = _obj(message.get("call"))
    call_id = str(call.get("id") or "") or None
    tool_calls = [c for c in message.get("toolCallList") or [] if isinstance(c, dict)]

    results: list[dict[str, Any]] = []
    allowed: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        function = _obj(tool_call.get("function"))
        name = str(function.get("name") or tool_call.get("name") or "")
        call_ref = str(tool_call.get("id") or "")
        decision = _decide(
            session,
            agent,
            name,
            _arguments(function.get("arguments", tool_call.get("arguments"))),
            session_id=call_id,
        )
        if _stopped(decision):
            results.append({"toolCallId": call_ref, "name": name, "error": refusal(decision)})
        else:
            allowed.append(tool_call)
    session.commit()

    if allowed:
        # The credential Vapi sent goes on with the call: registered as the connection's
        # secret, the token a tool server already checks keeps working unchanged.
        passed = {"content-type": "application/json"}
        if authorization:
            passed["authorization"] = authorization
        if x_vapi_secret:
            passed["x-vapi-secret"] = x_vapi_secret
        results.extend(_vapi_forward(connection, event, message, allowed, passed))
    order = {str(c.get("id") or ""): n for n, c in enumerate(tool_calls)}
    results.sort(key=lambda r: order.get(r["toolCallId"], len(order)))
    return JSONResponse({"results": results})


def _vapi_forward(
    connection: PlatformConnection,
    event: dict[str, Any],
    message: dict[str, Any],
    allowed: list[dict[str, Any]],
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    """Send the allowed calls on to the customer's tool server, as Vapi would have:
    the same message with only those calls in it."""
    ids = {str(c.get("id") or "") for c in allowed}
    forwarded = dict(message)
    forwarded["toolCallList"] = allowed
    if isinstance(message.get("toolWithToolCallList"), list):
        forwarded["toolWithToolCallList"] = [
            t
            for t in message["toolWithToolCallList"]
            if isinstance(t, dict) and str((t.get("toolCall") or {}).get("id") or "") in ids
        ]
    body = json.dumps({**event, "message": forwarded}).encode()
    try:
        response = connections.forward(connection, body, headers)
        answer = response.json() if response.status_code < 300 else None
    except (connections.ForwardFailed, ValueError) as exc:
        log.warning("vapi hook %s: forward failed: %s", connection.id, exc)
        answer = None
    upstream = answer.get("results") if isinstance(answer, dict) else None
    if not isinstance(upstream, list):
        return [
            {
                "toolCallId": str(c.get("id") or ""),
                "name": str((c.get("function") or {}).get("name") or ""),
                "error": "The tool could not be reached. Tell the caller to try again later.",
            }
            for c in allowed
        ]
    return [r for r in upstream if isinstance(r, dict) and str(r.get("toolCallId") or "") in ids]


# ---------------------------------------------------------------------------
# Retell
# ---------------------------------------------------------------------------

#: How far a signature's timestamp may be from now, as Retell's own verifier allows.
RETELL_SKEW_MS = 5 * 60 * 1000
_RETELL_SIGNATURE = re.compile(r"^v=(\d+),d=([0-9a-fA-F]+)$")


def retell_signature_valid(api_key: str, body: bytes, header: str | None, now_ms: int) -> bool:
    """``X-Retell-Signature: v=<ms timestamp>,d=<hex>``, where the digest is
    HMAC-SHA256 of the raw body followed by the timestamp, keyed with the Retell API
    key. A timestamp more than five minutes away is refused, so a captured delivery
    cannot be replayed later."""
    match = _RETELL_SIGNATURE.match((header or "").strip())
    if not match or not api_key:
        return False
    stamp, digest = match.groups()
    if abs(now_ms - int(stamp)) > RETELL_SKEW_MS:
        return False
    expected = hmac.new(api_key.encode(), body + stamp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest.lower())


def _retell_messages(call: dict[str, Any]) -> list[dict[str, Any]]:
    """The call's transcript so far, as chat messages, so an argument copied out of
    what the caller said is known to have come from the caller."""
    out = []
    for turn in call.get("transcript_object") or []:
        if isinstance(turn, dict) and isinstance(turn.get("content"), str):
            role = "assistant" if turn.get("role") == "agent" else "user"
            out.append({"role": role, "content": turn["content"]})
    return out


@router.post("/v1/hooks/retell/{connection_id}", summary="Govern a Retell agent's custom function")
def retell_hook(
    connection_id: str,
    body: bytes = Depends(_raw_body),
    session: Session = Depends(db),
    x_retell_signature: Annotated[str | None, Header()] = None,
    tool: str | None = None,
) -> Response:
    """A Retell custom function's URL. The call is decided after its signature is
    verified with the connection's Retell API key; a refusal is answered with 200 and
    the sentence for the agent to say (a non-2xx would be retried, then read to the
    model as an error), an allowed call is forwarded to the tool server with Retell's
    own body and signature, so the server's verification still holds.

    With "Payload: args only" the body carries no function name: add ``?tool=<name>``
    to the URL."""
    connection = _connection(session, connection_id, "retell")
    secret = connections.secret_of(connection) or ""
    if not retell_signature_valid(secret, body, x_retell_signature, int(time.time() * 1000)):
        raise HTTPException(401, "the Retell signature did not verify")
    event = _json_object(body)
    call = _obj(event.get("call"))
    if "args" in event or "name" in event:
        name, arguments = str(event.get("name") or tool or ""), _arguments(event.get("args"))
    else:
        name, arguments = str(tool or ""), event
    if not name:
        raise HTTPException(422, "no function name: add ?tool=<name> to an args-only URL")
    decision = _decide(
        session,
        _agent_slug(session, connection),
        name,
        arguments,
        session_id=str(call.get("call_id") or "") or None,
        messages=_retell_messages(call),
    )
    session.commit()
    if _stopped(decision):
        return JSONResponse({"result": refusal(decision)})
    headers = {"content-type": "application/json"}
    if x_retell_signature:
        headers["x-retell-signature"] = x_retell_signature
    try:
        response = connections.forward(connection, body, headers)
    except connections.ForwardFailed as exc:
        log.warning("retell hook %s: forward failed: %s", connection.id, exc)
        response = None
    if response is None or response.status_code >= 300:
        return JSONResponse(
            {"result": "The tool could not be reached. Tell the caller to try again later."}
        )
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json"),
    )


# ---------------------------------------------------------------------------
# Copilot Studio
# ---------------------------------------------------------------------------

#: `reasonCode` values in a Copilot Studio block (the provider chooses them).
REASON_POLICY = 100
REASON_APPROVAL = 101


def _copilot_error(status: int, code: int, message: str) -> JSONResponse:
    """Copilot Studio's ErrorResponse shape."""
    return JSONResponse(
        {"errorCode": code, "message": message, "httpStatus": status}, status_code=status
    )


def _copilot_authorised(
    request: Request, connection: PlatformConnection, authorization: str | None
) -> str | None:
    """None when the Entra token verifies for this connection; else why not."""
    from agentfox.platform.identity import entra

    if not (authorization and authorization.lower().startswith("bearer ")):
        return "no bearer token"
    config = connection.config_json or {}
    audience = config.get("audience") or f"{request.url.scheme}://{request.url.netloc}"
    try:
        entra.verify_app_token(
            authorization.split(" ", 1)[1].strip(),
            tenant_id=str(config.get("tenant_id") or ""),
            app_id=str(config.get("app_id") or ""),
            audiences={audience, str(config.get("audience_app_id") or "")} - {""},
        )
    except entra.TokenInvalid as exc:
        return str(exc)
    return None


@router.post(
    "/v1/hooks/copilot-studio/{connection_id}/validate",
    summary="Copilot Studio threat detection health check",
)
def copilot_validate(
    connection_id: str,
    request: Request,
    session: Session = Depends(db),
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Called when an admin saves the endpoint in the Power Platform admin center:
    answers OK when the connection exists and the token is the configured app's."""
    connection = _connection(session, connection_id, "copilot_studio")
    problem = _copilot_authorised(request, connection, authorization)
    if problem:
        return _copilot_error(401, 2003, f"authentication failed: {problem}")
    return JSONResponse({"isSuccessful": True, "status": "OK"})


def _copilot_messages(context: dict[str, Any]) -> list[dict[str, Any]]:
    """The planner's chat history, then each earlier tool's outputs as a tool message,
    so a value the agent copied out of a tool's output (an address read from a record)
    is known to be one."""
    out: list[dict[str, Any]] = []
    for item in context.get("chatHistory") or []:
        if isinstance(item, dict) and isinstance(item.get("content"), str):
            role = "assistant" if item.get("role") == "assistant" else "user"
            out.append({"role": role, "content": item["content"]})
    outputs = context.get("previousToolOutputs") or context.get("previousToolsOutputs") or []
    for item in outputs if isinstance(outputs, list) else []:
        if not isinstance(item, dict):
            continue
        values = item.get("outputs")
        values = values if isinstance(values, list) else [values]
        text = json.dumps(
            {v.get("name"): v.get("value") for v in values if isinstance(v, dict)}, default=str
        )
        out.append({"role": "tool", "name": str(item.get("toolName") or ""), "content": text})
    return out


@router.post(
    "/v1/hooks/copilot-studio/{connection_id}/analyze-tool-execution",
    summary="Copilot Studio: decide a planned tool call",
)
def copilot_analyze(
    connection_id: str,
    request: Request,
    body: bytes = Depends(_raw_body),
    session: Session = Depends(db),
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Each tool a generative-orchestration agent plans to run, before it runs.

    Answered with ``blockAction``. Copilot Studio cannot wait for a person, so a call
    that needs approval is blocked with that reason. Copilot Studio gives this a
    second; the decision is the deterministic tier (judges are deferred), well under
    it."""
    connection = _connection(session, connection_id, "copilot_studio")
    problem = _copilot_authorised(request, connection, authorization)
    if problem:
        return _copilot_error(401, 2003, f"authentication failed: {problem}")
    try:
        event = _json_object(body)
    except HTTPException:
        return _copilot_error(400, 4000, "the body is not a JSON object")
    tool_def = event.get("toolDefinition")
    if not isinstance(tool_def, dict) or not (tool_def.get("name") or tool_def.get("id")):
        return _copilot_error(400, 4001, "Missing required field: toolDefinition")
    context = _obj(event.get("plannerContext"))
    metadata = _obj(event.get("conversationMetadata"))
    decision = _decide(
        session,
        _agent_slug(session, connection),
        str(tool_def.get("name") or tool_def.get("id")),
        _arguments(event.get("inputValues")),
        session_id=str(metadata.get("conversationId") or "") or None,
        messages=_copilot_messages(context),
    )
    if not _stopped(decision):
        return JSONResponse({"blockAction": False})
    held = decision.get("verdict") == "escalate"
    return JSONResponse(
        {
            "blockAction": True,
            "reasonCode": REASON_APPROVAL if held else REASON_POLICY,
            "reason": (
                "This action needs a person's approval. It has been sent for approval and "
                "will run when it is asked for again after that."
                if held
                else "This action is not allowed by your organisation's AgentFox policy."
            ),
            # Copilot Studio wants this pre-serialised.
            "diagnostics": json.dumps(
                {
                    "decision_id": decision.get("decision_id"),
                    "trace_id": decision.get("trace_id"),
                    "approval_id": decision.get("approval_id"),
                }
            ),
        }
    )


# ---------------------------------------------------------------------------
# Control plane: registering a connection
# ---------------------------------------------------------------------------


class ConnectionIn(BaseModel):
    platform: str
    #: The customer's own tool server (Vapi and Retell).
    upstream_url: str | None = None
    #: Retell: the Retell API key it signs with. Vapi: the token its credential sends
    #: (the one the tool server already checks, which is passed on with each allowed
    #: call); made when omitted.
    secret: str | None = None
    #: Copilot Studio: ``tenant_id`` and ``app_id`` of the Entra app it signs in with.
    config: dict[str, Any] = Field(default_factory=dict)


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@admin_router.post("/agents/{slug}/platform-connections", status_code=201)
def create_connection(
    slug: str,
    payload: ConnectionIn,
    request: Request,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Register the agent as running on Vapi, Retell or Copilot Studio. The answer's
    ``hook_url`` is what to paste into the platform; a Vapi ``secret`` made here is
    shown once."""
    agent = session.query(Agent).filter(Agent.slug == slug).one_or_none()
    if agent is None:
        raise HTTPException(404, "unknown agent")
    try:
        connection, made = connections.create(
            session,
            agent,
            payload.platform,
            upstream_url=payload.upstream_url,
            secret=payload.secret,
            config=payload.config,
            actor=user.email or user.id,
        )
    except connections.ConnectionError_ as exc:
        raise HTTPException(422, str(exc)) from exc
    except EncryptionNotConfigured as exc:
        raise HTTPException(
            503,
            "this deployment cannot store the connection's secret: set "
            "AGENTFOX_TOKEN_ENCRYPTION_KEY",
        ) from exc
    chain.append(
        session,
        "platform_connection.created",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="agent",
        subject_id=agent.id,
        payload={
            "connection": connection.id,
            "platform": connection.platform,
            "upstream_url": connection.upstream_url,
        },
    )
    session.commit()
    out = connections.to_json(connection, _base_url(request))
    if made:
        out["secret"] = made
        out["note"] = "Put this secret in a Vapi Bearer credential; it is shown once."
    return out


@admin_router.get("/agents/{slug}/platform-connections")
def list_connections(
    slug: str,
    request: Request,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    agent = session.query(Agent).filter(Agent.slug == slug).one_or_none()
    if agent is None:
        raise HTTPException(404, "unknown agent")
    base = _base_url(request)
    return {
        "connections": [connections.to_json(c, base) for c in connections.for_agent(session, agent)]
    }


@admin_router.delete("/agents/{slug}/platform-connections/{connection_id}")
def delete_connection(
    slug: str,
    connection_id: str,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    """Disable a connection. Its hook URL answers 404 from then on; the row is kept
    for the audit trail."""
    agent = session.query(Agent).filter(Agent.slug == slug).one_or_none()
    connection = session.get(PlatformConnection, connection_id)
    if agent is None or connection is None or connection.agent_id != agent.id:
        raise HTTPException(404, "unknown connection")
    connection.enabled = False
    chain.append(
        session,
        "platform_connection.disabled",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="agent",
        subject_id=agent.id,
        payload={"connection": connection.id, "platform": connection.platform},
    )
    session.commit()
    return {"id": connection.id, "enabled": False}
