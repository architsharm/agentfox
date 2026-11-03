"""AgentFox interceptor for an Amazon Bedrock AgentCore Gateway.

Attached to a gateway as its REQUEST interceptor, this Lambda sees every MCP request
before the gateway sends it to a target. A ``tools/call`` is decided by AgentFox
(``POST /v1/guard/tool_call``) as a call of the configured agent; a blocked or held
call is answered by the gateway with an error and never reaches the target, an
allowed one passes through unchanged. Every other MCP method passes through.

Standard library only, so the deployment package is this one file.

Environment:

* ``AGENTFOX_URL`` — the gateway's base URL (``https://api.example.com``).
* ``AGENTFOX_AGENT`` — the agent the calls are governed as (its slug).
* ``AGENTFOX_KEY`` — that agent's key (``nom_agt_…``). Put it in Secrets Manager and
  pass it in with a dynamic reference (see ``template.yaml``).
* ``AGENTFOX_FAIL_MODE`` — ``closed`` (the default: a call AgentFox could not decide
  is refused) or ``open`` (it runs).
* ``AGENTFOX_BLOCK_STYLE`` — how a refusal reaches the agent: ``jsonrpc_error`` (the
  default: a JSON-RPC error with status 403) or ``tool_error`` (a tool result with
  ``isError: true``, which the model reads like any tool output).
* ``AGENTFOX_TIMEOUT_S`` — how long to wait for a decision (default 5).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

STOPPING_VERDICTS = {"block", "escalate", "abstain"}

#: AgentCore names a tool `<target>___<tool>`; the policy knows the tool's own name.
TARGET_SEPARATOR = "___"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _pass_through(body: Any) -> dict[str, Any]:
    return {"interceptorOutputVersion": "1.0", "mcp": {"transformedGatewayRequest": {"body": body}}}


def _refuse(request_id: Any, message: str) -> dict[str, Any]:
    if _env("AGENTFOX_BLOCK_STYLE", "jsonrpc_error") == "tool_error":
        status, body = (
            200,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": message}], "isError": True},
            },
        )
    else:
        status, body = (
            403,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": message},
            },
        )
    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {"transformedGatewayResponse": {"statusCode": status, "body": body}},
    }


def refusal(decision: dict[str, Any]) -> str:
    if decision.get("verdict") == "escalate" and decision.get("approval_id"):
        return (
            "This action was not done: it needs a person to approve it and has been sent "
            f"for approval (approval id {decision['approval_id']}). Once approved, the same "
            "call goes through when it is made again."
        )
    return "This action was not done: it is not allowed by this organisation's policy."


def _decide(tool: str, arguments: dict[str, Any], session_id: str | None) -> dict[str, Any]:
    payload = {
        "agent": _env("AGENTFOX_AGENT"),
        "tool": tool,
        "arguments": arguments,
        "session_id": session_id,
        # The gateway cannot carry an approval id back: once a person approves a held
        # call, the same call (agent, tool, arguments) is let through once.
        "redeem_approved": True,
    }
    request = urllib.request.Request(
        _env("AGENTFOX_URL").rstrip("/") + "/v1/guard/tool_call",
        data=json.dumps(payload).encode(),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_env('AGENTFOX_KEY')}",
        },
        method="POST",
    )
    timeout = float(_env("AGENTFOX_TIMEOUT_S", "5") or 5)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured URL
        return json.loads(response.read() or b"{}")


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    mcp = event.get("mcp") or {}
    if mcp.get("gatewayResponse") is not None:
        # Attached as a RESPONSE interceptor too: leave the target's answer as it is.
        response = mcp["gatewayResponse"]
        return {
            "interceptorOutputVersion": "1.0",
            "mcp": {
                "transformedGatewayResponse": {
                    "statusCode": response.get("statusCode", 200),
                    "body": response.get("body"),
                }
            },
        }
    request = mcp.get("gatewayRequest") or {}
    body = request.get("body")
    if not isinstance(body, dict) or body.get("method") != "tools/call":
        return _pass_through(body)
    params = body.get("params") or {}
    name = str(params.get("name") or "")
    tool = name.split(TARGET_SEPARATOR, 1)[1] if TARGET_SEPARATOR in name else name
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    headers = {str(k).lower(): v for k, v in (request.get("headers") or {}).items()}
    try:
        decision = _decide(tool, arguments, headers.get("mcp-session-id"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        if _env("AGENTFOX_FAIL_MODE", "closed") == "open":
            print(json.dumps({"agentfox": "undecided, allowed (fail open)", "error": str(exc)}))
            return _pass_through(body)
        print(json.dumps({"agentfox": "undecided, refused (fail closed)", "error": str(exc)}))
        return _refuse(body.get("id"), "This action was not done: it could not be checked.")
    if str(decision.get("verdict")) in STOPPING_VERDICTS:
        return _refuse(body.get("id"), refusal(decision))
    return _pass_through(body)
