"""A guardrail must not perform the disclosure it was installed to prevent.

Asking a hosted model whether a string contains personal data sends the string.
These tests pin the gate that stops that: default-local, egress-gated, redacted
when permitted, and failing closed when it cannot verify what it would send.
"""

from __future__ import annotations

import pytest

from agentfox.config import get_settings
from agentfox.judgment import (
    Backend,
    EgressRefused,
    JevClient,
    JevResult,
    JevUnavailable,
    JudgmentGateway,
)

SENSITIVE = {
    "note": "Contact bob@example.com, SSN 123-45-6789, about order 4471.",
    "api_key": "sk-live-not-a-real-key",
}
QUESTION = {"q": {"type": "noul", "instructions": "anything?", "criteria": {"what": "x"}}}


class CapturingClient(JevClient):
    """Records what would have gone over the wire instead of sending it."""

    def __init__(self) -> None:
        super().__init__(api_key="test-key")
        self.sent: list = []

    def available(self) -> bool:
        return True

    def ask(self, state, questions):  # type: ignore[override]
        self.sent.append(state)
        return JevResult(model="test")


@pytest.fixture
def egress_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_egress", True)


def test_the_default_backend_sends_nothing() -> None:
    """Zero egress by default has to include judgment, or it isn't zero."""
    client = CapturingClient()
    with pytest.raises(EgressRefused):
        JudgmentGateway(client).ask(SENSITIVE, QUESTION)
    assert client.sent == []


def test_remote_is_refused_while_allow_egress_is_off() -> None:
    client = CapturingClient()
    gate = JudgmentGateway(client, backend=Backend.REMOTE)
    with pytest.raises(EgressRefused, match="allow_egress"):
        gate.ask(SENSITIVE, QUESTION)
    assert client.sent == []


def test_a_refusal_is_an_outage_not_an_authorisation() -> None:
    """EgressRefused must stay a JevUnavailable.

    The router treats JevUnavailable as UNKNOWN and never as a pass. If a
    refusal were its own exception type, a caller could catch it separately
    and get the failure mode backwards.
    """
    assert issubclass(EgressRefused, JevUnavailable)


def test_pii_is_redacted_before_it_leaves(egress_on) -> None:
    client = CapturingClient()
    gate = JudgmentGateway(client, backend=Backend.REMOTE)
    gate.ask(SENSITIVE, QUESTION)

    (sent,) = client.sent
    blob = str(sent)
    assert "bob@example.com" not in blob
    assert "123-45-6789" not in blob
    # the question stays answerable: structure and non-PII context survive
    assert "order 4471" in blob


def test_secret_fields_are_dropped_whatever_the_detectors_say(egress_on) -> None:
    """A credential is not an entity type; name-based withholding covers it."""
    client = CapturingClient()
    JudgmentGateway(client, backend=Backend.REMOTE).ask(SENSITIVE, QUESTION)
    (sent,) = client.sent
    assert "sk-live-not-a-real-key" not in str(sent)
    assert sent["api_key"] == "<redacted>"


def test_nested_values_are_walked(egress_on) -> None:
    client = CapturingClient()
    state = {"outer": {"inner": ["mail bob@example.com", {"token": "abc123"}]}}
    JudgmentGateway(client, backend=Backend.REMOTE).ask(state, QUESTION)
    blob = str(client.sent[0])
    assert "bob@example.com" not in blob
    assert "abc123" not in blob


def test_it_fails_closed_when_the_redactor_is_missing(egress_on) -> None:
    """Unverifiable payloads are not sent. 'Could not check' != 'send anyway'."""
    client = CapturingClient()
    gate = JudgmentGateway(
        client, backend=Backend.REMOTE, detector=None, redact=True, fail_closed=True
    )
    gate._detector_tried = True  # simulate "tried to load, found nothing"
    gate._detector = None
    with pytest.raises(EgressRefused, match="fail_closed|unverified"):
        gate.ask(SENSITIVE, QUESTION)
    assert client.sent == []


def test_a_detector_fault_does_not_leak_the_payload(egress_on) -> None:
    class Exploding:
        def detect(self, text, context):
            raise RuntimeError("detector broke")

    client = CapturingClient()
    gate = JudgmentGateway(client, backend=Backend.REMOTE, detector=Exploding())
    with pytest.raises(EgressRefused):
        gate.ask(SENSITIVE, QUESTION)
    assert client.sent == []


def test_inspect_reports_without_sending(egress_on) -> None:
    client = CapturingClient()
    report = JudgmentGateway(client, backend=Backend.REMOTE).inspect(SENSITIVE)
    assert report.allowed
    assert report.redactions >= 1
    assert "api_key" in report.never_send_fields
    assert client.sent == []


def test_the_client_itself_refuses_with_egress_off() -> None:
    """Defence in depth: bypassing the gateway must not bypass the gate.

    This is the mistake the codebase already made once — presidio reaching the
    network from inside a guarded request while allow_egress was false.
    """
    with pytest.raises(JevUnavailable, match="allow_egress"):
        JevClient(api_key="test-key").ask({"a": 1}, QUESTION)


def test_no_questions_is_not_an_egress_event() -> None:
    client = CapturingClient()
    assert JudgmentGateway(client).ask(SENSITIVE, {}).answers == {}
    assert client.sent == []
