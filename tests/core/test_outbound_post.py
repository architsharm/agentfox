"""`outbound.guarded_post`: the same address vetting as a GET, and no redirect is followed."""

from __future__ import annotations

import socket

import httpx
import pytest

from agentfox.core import outbound


def _dns(address):
    return lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]


def test_a_post_reaches_the_vetted_address_with_its_body(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(outbound, "_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setattr(outbound, "_getaddrinfo", _dns("93.184.216.34"))
    resp = outbound.guarded_post(
        "https://mcp.example.com/mcp", what="x", json_body={"a": 1}, max_bytes=1000
    )
    assert resp.json() == {"ok": True}
    assert seen[0].method == "POST" and seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "mcp.example.com"
    assert seen[0].content == b'{"a":1}'


def test_a_post_is_never_redirected(monkeypatch):
    monkeypatch.setattr(
        outbound,
        "_TRANSPORT",
        httpx.MockTransport(
            lambda r: httpx.Response(307, headers={"location": "http://10.0.0.1/"})
        ),
    )
    monkeypatch.setattr(outbound, "_getaddrinfo", _dns("93.184.216.34"))
    with pytest.raises(outbound.OutboundRefused, match="redirect"):
        outbound.guarded_post("https://mcp.example.com/mcp", what="x", json_body={}, max_bytes=10)


def test_a_post_to_an_internal_address_is_refused(monkeypatch):
    monkeypatch.setattr(outbound, "_getaddrinfo", _dns("10.0.0.5"))
    with pytest.raises(outbound.OutboundRefused, match="internal address"):
        outbound.guarded_post("https://internal.example.com/", what="x", json_body={}, max_bytes=10)
