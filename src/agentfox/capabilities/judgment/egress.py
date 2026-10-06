"""Where a judgment is allowed to be made, and what may leave the box to make it.

A PII detector that posts the text to a third party to ask whether it contains
PII has not protected anything — it has performed the disclosure it was
installed to prevent. The same is true, less obviously, of asking a hosted
model whether a support reply leaks a customer's address: the address is in
the question.

`JevClient` did not check `allow_egress`. Every other outbound caller in this
codebase does (`providers/remote.py`, `providers/enterprise.py`,
`webhooks.py`), and `adapters/presidio.py` carries a docstring about exactly
this failure — a dependency reaching the network from inside a guarded request
while "`allow_egress` was false throughout; it gates our own outbound calls and
never saw this one." This module is that gate for judgment.

Three settings, because operators want different things:

    Backend.LOCAL    nothing leaves, ever. Questions no local detector can
                     answer come back UNKNOWN, which the router already treats
                     as "not authorised" rather than "fine".
    Backend.REMOTE   send to Jev, but only with `allow_egress` on, and only
                     after redaction.
    Backend.AUTO     local where a local detector covers the question, remote
                     for the rest, subject to the same gate.

**Redaction is what makes remote mode defensible.** Before any payload leaves,
the local PII detector runs over every string in the state and its findings are
masked. What goes out is `"email <PII.EMAIL> about order 4471"`, not the
address. For PII work this is not self-defeating: masking what the local
detector *found* still lets the remote model find what it *missed*, which the
benchmark says is most of it — the local default reaches 17.8% presence recall
against Jev's 97.9%. The recall gain survives; the data does not travel.

**Failing closed is deliberate.** If redaction is requested and the detector
cannot load, the payload is not sent. An unverified payload is the case this
module exists to prevent, so "we could not check" has to mean "we do not send"
and not "send it anyway".
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from agentfox.capabilities.judgment.jev import JevClient, JevResult, JevUnavailable
from agentfox.core.config import get_settings

log = logging.getLogger(__name__)


class Backend(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"
    AUTO = "auto"


class PiiEgress(StrEnum):
    """What happens when the payload turns out to contain personal data.

    An explicit three-way operator choice rather than a single boolean,
    because the right answer genuinely differs by deployment:

        BLOCK    nothing containing detected PII leaves, redacted or not.
                 The judgment is simply not made remotely. Pick this for
                 regulated data; it is the only setting under which a remote
                 tier cannot disclose a subject's data.
        REDACT   mask what the local detector finds and send the remainder
                 (default). Measured cost: about one point of the recall gain
                 remote judgment exists for. Measured residual: the ~82% of
                 PII the local detector does not find still leaves.
        ALLOW    send as-is. A deliberate downgrade, logged at warning.
    """

    BLOCK = "block"
    REDACT = "redact"
    ALLOW = "allow"


class EgressRefused(JevUnavailable):
    """The judgment was not made because the payload was not allowed to leave.

    Deliberately a `JevUnavailable`: the router already treats that as UNKNOWN
    and never as authorisation, so a refusal degrades exactly like an outage
    instead of needing a second code path that might forget to fail closed.
    """


#: Field names whose value never leaves this process regardless of redaction —
#: a secret is not PII and the entity detectors are not looking for it.
NEVER_SEND = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|credential|"
    r"private[_-]?key|session[_-]?id|cookie)",
    re.I,
)
REDACTED = "<redacted>"


class SpanDetector(Protocol):
    """Just enough of the detector interface to mask with."""

    def detect(self, text: str, context: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class EgressReport:
    allowed: bool
    reason: str
    redactions: int = 0
    never_send_fields: tuple[str, ...] = ()
    payload: Any = None


@dataclass(slots=True)
class _Masker:
    detector: SpanDetector | None
    context: Any
    count: int = 0
    fields: list[str] = field(default_factory=list)

    def text(self, value: str) -> str:
        if not self.detector or not value:
            return value
        try:
            found = self.detector.detect(value, self.context).detections
        except Exception as exc:  # noqa: BLE001 - a detector fault must not leak
            raise EgressRefused(f"redaction failed, not sending: {type(exc).__name__}") from exc
        spans = sorted(
            ((d.start, d.end, d.entity_type) for d in found if d.start is not None),
            reverse=True,
        )
        out = value
        for start, end, kind in spans:
            if start < 0 or end > len(out) or start >= end:
                continue
            out = f"{out[:start]}<{kind}>{out[end:]}"
            self.count += 1
        return out

    def walk(self, node: Any, path: str = "") -> Any:
        if isinstance(node, dict):
            masked = {}
            for k, v in node.items():
                here = f"{path}.{k}" if path else str(k)
                if NEVER_SEND.search(str(k)):
                    self.fields.append(here)
                    masked[k] = REDACTED
                else:
                    masked[k] = self.walk(v, here)
            return masked
        if isinstance(node, (list, tuple)):
            return [self.walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
        if isinstance(node, str):
            return self.text(node)
        return node


class JudgmentGateway:
    """Decides whether a judgment may be made remotely, and sanitises it if so.

    The gateway is the only thing that should call `JevClient.ask()` in product
    code. Calling the client directly bypasses both the egress gate and
    redaction, which is how this problem arose in the first place.
    """

    def __init__(
        self,
        client: JevClient | None = None,
        *,
        backend: Backend | str | None = None,
        detector: SpanDetector | None = None,
        redact: bool = True,
        fail_closed: bool = True,
        pii_egress: PiiEgress | str | None = None,
        local_answerable: Iterable[str] = (),
    ) -> None:
        self._client = client
        self._backend = Backend(backend) if backend else _effective_backend()
        self._redact = redact
        self._fail_closed = fail_closed
        self._local_answerable = set(local_answerable)
        self._pii_egress = PiiEgress(pii_egress) if pii_egress else None
        self._detector = detector
        self._detector_tried = detector is not None

    def _pii_mode(self) -> PiiEgress:
        """The PII rule in force: explicit argument, else the effective posture.

        Posture rather than settings directly, so an admin who tightened this tenant
        to `block` in the dashboard is obeyed by the gate and not only by the page
        that displays it. Posture can only ever be stricter than the deployment's
        own value, so reading it here cannot loosen anything.
        """
        if self._pii_egress is not None:
            return self._pii_egress
        from agentfox.capabilities.judgment import posture as _posture

        return _posture.effective().pii_egress

    # -- redaction ---------------------------------------------------------
    def _local_detector(self) -> SpanDetector | None:
        if not self._detector_tried:
            self._detector_tried = True
            try:
                from agentfox.detection.detectors.pii import NativePiiDetector

                self._detector = NativePiiDetector()
            except Exception as exc:  # noqa: BLE001
                log.warning("judgment: no local redactor available (%s)", type(exc).__name__)
                self._detector = None
        return self._detector

    def _context(self) -> Any:
        try:
            from agentfox.detection.base import DetectionContext

            return DetectionContext(surface="input")
        except Exception:  # noqa: BLE001
            return None

    # -- the gate ----------------------------------------------------------
    def inspect(self, state: Any) -> EgressReport:
        """What would happen to this payload, without sending it."""
        if self._backend is Backend.LOCAL:
            return EgressReport(False, "backend is local; judgment never leaves the process")
        if not getattr(get_settings(), "allow_egress", False):
            return EgressReport(False, "allow_egress is off")
        if self._client is None or not self._client.available():
            return EgressReport(False, "no judgment client configured")
        mode = self._pii_mode()
        if mode is PiiEgress.ALLOW and not self._redact:
            log.warning("judgment: sending unredacted payload (judgment_pii_egress=allow)")
            return EgressReport(
                True, "sending unredacted (pii egress policy: allow)", payload=state
            )

        detector = self._local_detector()
        if detector is None and self._fail_closed:
            return EgressReport(
                False,
                "redaction requested but no local detector is available, and "
                "fail_closed is set; an unverified payload is not sent",
            )
        masker = _Masker(detector, self._context())
        payload = masker.walk(state)
        if mode is PiiEgress.BLOCK and masker.count:
            return EgressReport(
                False,
                f"payload contains {masker.count} detected personal-data span(s) and "
                "judgment_pii_egress is 'block'; the judgment is not made remotely",
                redactions=masker.count,
                never_send_fields=tuple(masker.fields),
            )
        return EgressReport(
            True,
            f"redacted {masker.count} span(s)",
            redactions=masker.count,
            never_send_fields=tuple(masker.fields),
            payload=payload,
        )

    def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> JevResult:
        """Make the judgment, or refuse. Never sends an unchecked payload."""
        if not questions:
            return JevResult()
        report = self.inspect(state)
        if not report.allowed:
            raise EgressRefused(report.reason)
        if report.never_send_fields:
            log.info("judgment: withheld fields %s", list(report.never_send_fields))
        if report.redactions:
            log.info("judgment: redacted %d span(s) before egress", report.redactions)
        assert self._client is not None  # inspect() established this
        return self._client.ask(report.payload, questions)


def _setting(name: str, default: str) -> str:
    return str(getattr(get_settings(), name, default) or default)


def _effective_backend() -> Backend:
    """The backend the active posture selects, clamped by the deployment's ceiling."""
    from agentfox.capabilities.judgment import posture as _posture

    return _posture.effective().backend
