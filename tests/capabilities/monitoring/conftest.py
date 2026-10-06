"""Fakes for monitoring tests: a GitHub that serves tarballs, DNS for `core.outbound`,
and a Slack that records what it was sent. No test here touches the network."""

from __future__ import annotations

import datetime as dt
import io
import json
import socket
import tarfile

import httpx
import pytest
from cryptography.fernet import Fernet

from agentfox.capabilities.monitoring import alerts
from agentfox.capabilities.monitoring import github as gh
from agentfox.core import outbound
from agentfox.core.config import get_settings

T0 = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def tarball(files: dict[str, str], top: str = "acme-bot-abc123") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{top}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeGitHub:
    """Serves `GET /repos/{repo}/tarball[/{ref}]` from `self.files`; records requests."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.status = 200
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "nope"})
        if "/tarball" in request.url.path:
            return httpx.Response(200, content=tarball(self.files))
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 42, "login": "octo"})
        return httpx.Response(404)


@pytest.fixture
def fake_github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(gh, "_TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "token_encryption_key", key)
    return key


class FakeWeb:
    """Answers DNS with a public address and serves registered paths through
    `core.outbound`'s injectable transport."""

    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404)
        if callable(route):
            return route(request)
        if isinstance(route, int):
            return httpx.Response(route)
        return httpx.Response(200, json=route)


@pytest.fixture
def fake_web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(outbound, "_TRANSPORT", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(
        outbound,
        "_getaddrinfo",
        lambda host, port, type=0: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    return fake


@pytest.fixture
def slack(monkeypatch):
    """Records Slack posts instead of sending them."""
    sent: list[tuple[str, dict]] = []

    def _post(url, raw, timeout):
        sent.append((url, json.loads(raw)))
        return 200

    monkeypatch.setattr(alerts, "post", _post)
    alerts.reset_alert_state()
    yield sent
    alerts.wait_for_delivery(5)
