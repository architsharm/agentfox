"""Read a remote MCP server's tool listing over Streamable HTTP, and nothing else.

Three JSON-RPC messages: ``initialize``, ``notifications/initialized`` and
``tools/list`` (following ``nextCursor``). No tool is ever called. Every request goes
through `core.outbound`, so a server URL that resolves to this deployment's own
network or to cloud metadata is refused the same way an OpenAPI spec URL is.

A stdio server cannot be read this way — AgentFox never starts a server process — so
its listing still has to be pushed (`agentfox scan mcp NAME --file tools.json` or
`POST /api/mcp-servers/{name}/tools`).
"""

from __future__ import annotations

import json
from typing import Any

from agentfox.core import outbound

PROTOCOL_VERSION = "2025-06-18"
_MAX_BYTES = 2 * 1024 * 1024
_MAX_PAGES = 10
#: Transports a listing can be fetched over. The older SSE transport needs a held-open
#: event stream and is not supported; stdio is never started.
LIVE_TRANSPORTS = ("http", "streamable-http", "streamable_http", "streamable http")


class McpListingError(RuntimeError):
    """The listing could not be read: refused, unreachable, or not an MCP answer."""


def can_fetch(url: str, transport: str) -> bool:
    return url.startswith(("http://", "https://")) and (transport or "").lower() in LIVE_TRANSPORTS


def _decode(resp: Any, request_id: int) -> dict[str, Any]:
    content_type = resp.headers.get("content-type", "")
    text = resp.text
    candidates: list[str] = []
    if "text/event-stream" in content_type:
        for line in text.splitlines():
            if line.startswith("data:"):
                candidates.append(line[5:].strip())
    else:
        candidates.append(text)
    for raw in candidates:
        try:
            message = json.loads(raw)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            if "error" in message:
                raise McpListingError(f"the server answered with an error: {message['error']}")
            result = message.get("result")
            if isinstance(result, dict):
                return result
    raise McpListingError("the server's answer was not a JSON-RPC result for the request")


def fetch_tools(url: str, *, timeout: float = 20.0) -> list[dict[str, Any]]:
    """The server's current ``tools/list``, as a list of tool descriptors."""
    headers = {"Accept": "application/json, text/event-stream"}

    def post(body: dict[str, Any], extra: dict[str, str]) -> Any:
        try:
            return outbound.guarded_post(
                url,
                what="the MCP server",
                json_body=body,
                max_bytes=_MAX_BYTES,
                timeout=timeout,
                headers={**headers, **extra},
            )
        except outbound.OutboundRefused as exc:
            raise McpListingError(str(exc)) from exc

    init = post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agentfox-monitor", "version": "1"},
            },
        },
        {},
    )
    _decode(init, 1)
    session_headers: dict[str, str] = {}
    session_id = init.headers.get("mcp-session-id")
    if session_id:
        session_headers["Mcp-Session-Id"] = session_id
    session_headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session_headers)

    tools: list[dict[str, Any]] = []
    cursor: str | None = None
    for page in range(_MAX_PAGES):
        request_id = 2 + page
        params: dict[str, Any] = {"cursor": cursor} if cursor else {}
        resp = post(
            {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": params},
            session_headers,
        )
        result = _decode(resp, request_id)
        listed = result.get("tools")
        if not isinstance(listed, list):
            raise McpListingError("tools/list returned no `tools` array")
        tools.extend(t for t in listed if isinstance(t, dict))
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return tools
