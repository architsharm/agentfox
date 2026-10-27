"""Hosted providers call through one pooled client, so a judge call on the request
path reuses a kept-alive connection instead of paying TCP and TLS handshakes."""

from __future__ import annotations

import httpx

from agentfox.platform.providers import base, remote
from agentfox.platform.providers.base import CompletionRequest
from agentfox.platform.providers.remote import OpenAIProvider


def test_one_client_for_the_process():
    assert base.http() is base.http()


def test_every_completion_goes_through_the_shared_client(monkeypatch):
    seen: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "q1: 3"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(remote, "http", lambda: client)
    provider = OpenAIProvider()
    for timeout in (4.0, 2.5):
        reply = provider.complete(
            CompletionRequest(messages=[{"role": "user", "content": "x"}], timeout_s=timeout)
        )
        assert reply.text == "q1: 3"
    assert seen == [4.0, 2.5]  # each call keeps its own deadline on the shared client
