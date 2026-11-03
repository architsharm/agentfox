"""The AgentCore Gateway interceptor Lambda (`deploy/aws-agentcore-interceptor`).

It asks AgentFox about every MCP `tools/call` and answers in the interceptor's own
envelope: the request passed through untouched, or a response the gateway returns
instead of calling the target. Anything that is not a tool call passes through, and a
call AgentFox could not decide follows the configured fail mode.
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

HANDLER = Path(__file__).parents[3] / "deploy" / "aws-agentcore-interceptor" / "handler.py"


@pytest.fixture
def interceptor(monkeypatch):
    spec = importlib.util.spec_from_file_location("agentcore_interceptor", HANDLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setenv("AGENTFOX_URL", "https://agentfox.example.com/")
    monkeypatch.setenv("AGENTFOX_AGENT", "claims-agent")
    monkeypatch.setenv("AGENTFOX_KEY", "nom_agt_test")
    sent: list[dict[str, Any]] = []
    verdict = {"verdict": "allow"}

    def urlopen(request, timeout):
        if isinstance(verdict.get("raise"), Exception):
            raise verdict["raise"]
        sent.append(
            {
                "url": request.full_url,
                "auth": request.get_header("Authorization"),
                "body": json.loads(request.data),
            }
        )
        return io.BytesIO(json.dumps(verdict).encode())

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    return module, sent, verdict


def _event(method: str, **params: Any) -> dict[str, Any]:
    return {
        "interceptorInputVersion": "1.0",
        "mcp": {
            "gatewayRequest": {
                "path": "/mcp",
                "httpMethod": "POST",
                "headers": {"Mcp-Session-Id": "sess-1", "Authorization": "Bearer client"},
                "body": {"jsonrpc": "2.0", "id": 7, "method": method, "params": params},
            }
        },
    }


def test_an_allowed_tool_call_passes_through_unchanged(interceptor):
    module, sent, _ = interceptor
    event = _event("tools/call", name="Claims___lookup_claim", arguments={"id": "c1"})
    out = module.handler(event)
    assert out == {
        "interceptorOutputVersion": "1.0",
        "mcp": {"transformedGatewayRequest": {"body": event["mcp"]["gatewayRequest"]["body"]}},
    }
    assert sent == [
        {
            "url": "https://agentfox.example.com/v1/guard/tool_call",
            "auth": "Bearer nom_agt_test",
            "body": {
                "agent": "claims-agent",
                "tool": "lookup_claim",  # without the gateway's target prefix
                "arguments": {"id": "c1"},
                "session_id": "sess-1",
            },
        }
    ]


def test_a_blocked_call_is_answered_by_the_gateway_with_the_request_id(interceptor):
    module, _, verdict = interceptor
    verdict["verdict"] = "block"
    out = module.handler(_event("tools/call", name="Claims___pay_claim", arguments={}))
    response = out["mcp"]["transformedGatewayResponse"]
    assert response["statusCode"] == 403
    assert response["body"]["id"] == 7
    assert "not allowed" in response["body"]["error"]["message"]
    assert "transformedGatewayRequest" not in out["mcp"]


def test_tool_error_style_returns_a_result_the_model_reads(interceptor, monkeypatch):
    module, _, verdict = interceptor
    verdict.update(verdict="escalate", approval_id="apr_1")
    monkeypatch.setenv("AGENTFOX_BLOCK_STYLE", "tool_error")
    out = module.handler(_event("tools/call", name="pay_claim", arguments={}))
    response = out["mcp"]["transformedGatewayResponse"]
    assert response["statusCode"] == 200
    assert response["body"]["result"]["isError"] is True
    assert "apr_1" in response["body"]["result"]["content"][0]["text"]


def test_other_methods_pass_through_without_asking(interceptor):
    module, sent, _ = interceptor
    out = module.handler(_event("tools/list"))
    assert "transformedGatewayRequest" in out["mcp"] and sent == []


def test_a_response_interception_leaves_the_targets_answer_alone(interceptor):
    module, sent, _ = interceptor
    event = _event("tools/call", name="x")
    event["mcp"]["gatewayResponse"] = {"statusCode": 200, "body": {"jsonrpc": "2.0", "id": 7}}
    out = module.handler(event)
    assert out["mcp"]["transformedGatewayResponse"]["body"] == {"jsonrpc": "2.0", "id": 7}
    assert sent == []


@pytest.mark.parametrize(("mode", "refused"), [("closed", True), ("open", False), ("", True)])
def test_an_undecided_call_follows_the_fail_mode(interceptor, monkeypatch, mode, refused):
    module, _, verdict = interceptor
    verdict["raise"] = urllib.error.URLError("unreachable")
    if mode:
        monkeypatch.setenv("AGENTFOX_FAIL_MODE", mode)
    out = module.handler(_event("tools/call", name="lookup_claim", arguments={}))
    assert ("transformedGatewayResponse" in out["mcp"]) is refused
