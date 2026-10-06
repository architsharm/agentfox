"""Slack alerts for monitor findings: a short message when one opens, reopens or closes.

The deployment-wide finding webhook (`core.webhooks`) already sends every committed
finding at or above `webhook_min_severity`, monitor findings included, as signed JSON
for machines. This adds the message a person reads: one line of what happened, where,
and a link to the finding.

Two places a message can go, both optional:

* `slack_webhook_url` (``AGENTFOX_SLACK_WEBHOOK_URL``) — the deployment's own channel,
  filtered by `slack_min_severity`;
* a tenant's own incoming webhook (`AlertChannel`, set with ``PUT /api/alerts/slack``),
  stored encrypted and restricted to ``https://hooks.slack.com/`` so a tenant cannot
  point this server at an arbitrary address.

The same rules as the finding webhook:

* **Egress is egress.** With `allow_egress` off nothing is sent: a message carries
  finding titles out of the deployment.
* **Nothing is sent for work that did not happen.** Messages are queued on the session
  and delivered only after it commits; a rollback discards them.
* **Delivery never blocks or fails the caller.** One daemon worker, a bounded queue,
  failures logged and swallowed.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from agentfox import __version__
from agentfox.core.config import get_settings
from agentfox.core.models import AlertChannel, Finding, Monitor

log = logging.getLogger(__name__)

SLACK_HOST = "hooks.slack.com"
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
EVENT_LABELS = {
    "finding.created": "New",
    "finding.reopened": "Back",
    "finding.resolved": "Cleared",
}
_INFO_KEY = "agentfox_slack_alerts"
_QUEUE_MAX = 500

_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=_QUEUE_MAX)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_egress_notice_logged = False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def is_slack_webhook(url: str) -> bool:
    parts = urlsplit(url or "")
    return (
        parts.scheme == "https"
        and parts.hostname == SLACK_HOST
        and parts.path.startswith("/services/")
    )


def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def finding_link(finding_id: str) -> str:
    base = (get_settings().console_url or "").rstrip("/")
    return f"{base}/app/findings/{finding_id}" if base else ""


def format_message(finding: Finding, event_name: str, monitor: Monitor | None) -> dict[str, Any]:
    """The Slack body: ``{"text": ...}``, two short lines."""
    label = EVENT_LABELS.get(event_name, event_name)
    severity = str(finding.severity or "").upper()
    head = f"*AgentFox* · {label} · {severity}: {_escape(finding.title)}"
    where = f"{monitor.kind} `{_escape(monitor.target)}`" if monitor is not None else ""
    link = finding_link(finding.id)
    tail = " · ".join(p for p in (where, f"<{link}|Open finding>" if link else finding.id) if p)
    return {"text": f"{head}\n{tail}"}


def _tenant_channel(session: Session) -> tuple[str, str] | None:
    row = session.scalar(
        select(AlertChannel).where(AlertChannel.kind == "slack", AlertChannel.enabled.is_(True))
    )
    if row is None or not row.url_encrypted:
        return None
    from agentfox.core.crypto import decrypt_secret

    try:
        url = decrypt_secret(row.url_encrypted)
    except Exception:  # an undecryptable channel must not stop the run
        log.warning("slack alert: the tenant's channel could not be decrypted", exc_info=True)
        return None
    if not is_slack_webhook(url):
        return None
    return url, row.min_severity


def targets(session: Session) -> list[tuple[str, str]]:
    """``(url, min_severity)`` for every channel this session's tenant alerts to."""
    global _egress_notice_logged
    settings = get_settings()
    out: list[tuple[str, str]] = []
    if settings.slack_webhook_url:
        out.append((settings.slack_webhook_url, settings.slack_min_severity))
    tenant = _tenant_channel(session)
    if tenant is not None:
        out.append(tenant)
    if out and not settings.allow_egress:
        if not _egress_notice_logged:
            _egress_notice_logged = True
            log.info(
                "A Slack alert channel is configured but egress is disabled "
                "(AGENTFOX_ALLOW_EGRESS=false); nothing will be sent."
            )
        return []
    return out


def queue_finding_alert(
    session: Session, finding: Finding, event_name: str, monitor: Monitor | None = None
) -> int:
    """Queue a Slack message for ``finding``; sent once the session commits.

    Returns how many channels it was queued for.
    """
    try:
        rank = SEVERITY_RANK.get(str(finding.severity or "").lower(), 0)
        body = format_message(finding, event_name, monitor)
        queued = 0
        for url, min_severity in targets(session):
            if rank < SEVERITY_RANK.get(min_severity, 2):
                continue
            session.info.setdefault(_INFO_KEY, []).append((url, body))
            queued += 1
        return queued
    except Exception:
        log.warning("slack alert: could not queue a message", exc_info=True)
        return 0


# ---------------------------------------------------------------------------
# Session listeners and delivery
# ---------------------------------------------------------------------------


def _after_commit(session: Session) -> None:
    for url, body in session.info.pop(_INFO_KEY, None) or []:
        _enqueue(url, body)


def _after_soft_rollback(session: Session, previous_transaction: Any) -> None:
    # Only a root rollback discards the transaction's messages. Messages are queued
    # outside any savepoint a monitor run uses, so a savepoint rolling back never
    # carries one with it.
    if getattr(previous_transaction, "parent", None) is None:
        session.info.pop(_INFO_KEY, None)


def install(factory: sessionmaker[Session]) -> sessionmaker[Session]:
    """Wire alert delivery into a session factory. Idempotent."""
    if getattr(factory, "_agentfox_alerts", False):
        return factory
    event.listen(factory, "after_commit", _after_commit)
    event.listen(factory, "after_soft_rollback", _after_soft_rollback)
    factory._agentfox_alerts = True  # type: ignore[attr-defined]
    return factory


def _ensure_worker() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="agentfox-alerts", daemon=True)
            _worker.start()


def _run_worker() -> None:
    while True:
        url, body = _queue.get()
        try:
            deliver(url, body)
        except Exception:  # pragma: no cover - deliver already swallows
            log.warning("slack alert: delivery crashed", exc_info=True)
        finally:
            _queue.task_done()


def _enqueue(url: str, body: dict[str, Any]) -> None:
    _ensure_worker()
    try:
        _queue.put_nowait((url, body))
    except queue.Full:
        log.warning("slack alert: queue full (%d); dropped a message", _QUEUE_MAX)


def _post(url: str, raw: bytes, timeout: float) -> int:
    request = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json", "User-Agent": f"agentfox/{__version__}"},
        method="POST",
    )
    with _opener.open(request, timeout=timeout) as response:
        return int(response.status)


#: Replaced in tests to capture what would be sent.
post: Callable[[str, bytes, float], int] = _post


def deliver(url: str, body: dict[str, Any]) -> tuple[bool, str]:
    """POST one message, with one retry on 5xx, timeout or connection error."""
    if urlsplit(url).scheme not in ("http", "https"):
        return False, "the Slack URL must be http(s)"
    raw = json.dumps(body, separators=(",", ":")).encode()
    timeout = get_settings().webhook_timeout_seconds
    detail = "not attempted"
    for attempt in (1, 2):
        try:
            status = post(url, raw, timeout)
            return True, f"HTTP {status}"
        except urllib.error.HTTPError as exc:
            detail = f"HTTP {exc.code}"
            retryable = exc.code >= 500
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            detail = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
            retryable = True
        if attempt == 1 and retryable:
            time.sleep(0.5)
            continue
        break
    parts = urlsplit(url)
    log.warning("slack alert: delivery to %s://%s failed: %s", parts.scheme, parts.netloc, detail)
    return False, detail


def wait_for_delivery(timeout: float = 5.0) -> bool:
    """Block until queued messages are sent. For tests and short-lived processes."""
    deadline = time.monotonic() + timeout
    with _queue.all_tasks_done:
        while _queue.unfinished_tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _queue.all_tasks_done.wait(remaining)
    return True


def send_test(session: Session) -> list[dict[str, Any]]:
    """Send a test message to every configured channel now. Never raises."""
    results = []
    settings = get_settings()
    if not settings.allow_egress:
        return [{"ok": False, "detail": "egress is disabled (AGENTFOX_ALLOW_EGRESS=false)"}]
    for url, _min in targets(session):
        ok, detail = deliver(url, {"text": "*AgentFox* · test message from your monitors"})
        parts = urlsplit(url)
        results.append({"channel": f"{parts.scheme}://{parts.netloc}", "ok": ok, "detail": detail})
    return results


def reset_alert_state() -> None:
    """Test hook: re-arm the once-only egress notice."""
    global _egress_notice_logged
    _egress_notice_logged = False
