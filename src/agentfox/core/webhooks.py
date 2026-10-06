"""Outbound webhooks for the finding lifecycle.

Every Finding committed at or above ``webhook_min_severity`` is POSTed to
``webhook_url`` as ``{"event": "finding.created", "finding": {...}, "org_id": ...,
"sent_at": ...}``. A committed change of status sends the same body with
``finding.resolved``, ``finding.suppressed`` or ``finding.reopened`` — a queue a
receiver can mirror has to say when something left it, not only when it arrived.

Three properties matter more than the delivery itself:

* **Nothing is sent for work that did not happen.** Findings are collected in
  ``after_flush`` and only delivered from ``after_commit``; a rollback discards them,
  and a finding rolled back inside a savepoint is no longer persistent at commit time
  and is skipped.
* **The committing code never waits on, or fails because of, the network.**
  Delivery runs on a single daemon worker behind a bounded queue. Every failure is
  logged at WARNING and swallowed.
* **Egress is still egress.** With ``allow_egress`` off, a configured URL sends
  nothing (logged once at INFO).

When ``webhook_secret`` is set, each request carries
``X-Nometria-Signature: sha256=<hex HMAC-SHA256 of the raw request body>``. The body
includes ``sent_at`` and the request carries ``X-Nometria-Timestamp`` (unix seconds),
so a receiver can reject stale replays. A retried delivery reuses the same body,
signature and ``X-Nometria-Delivery`` id, so receivers can de-duplicate on it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, sessionmaker

from agentfox import __version__
from agentfox.core.config import get_settings
from agentfox.core.models import Finding

log = logging.getLogger(__name__)

EVENT_FINDING_CREATED = "finding.created"
EVENT_FINDING_RESOLVED = "finding.resolved"
EVENT_FINDING_SUPPRESSED = "finding.suppressed"
EVENT_FINDING_REOPENED = "finding.reopened"

#: Status a finding moved *to* -> the event that announces it.
_STATUS_EVENTS = {
    "resolved": EVENT_FINDING_RESOLVED,
    "suppressed": EVENT_FINDING_SUPPRESSED,
    "open": EVENT_FINDING_REOPENED,
}
EVENT_TEST = "webhook.test"

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

#: session.info key holding (finding, snapshot, event) triples flushed in the current
#: transaction.
_INFO_KEY = "agentfox_webhook_findings"
_QUEUE_MAX = 1000
_RETRY_BACKOFF_SECONDS = 0.5

_queue: queue.Queue[tuple[_Target, dict[str, Any]]] = queue.Queue(maxsize=_QUEUE_MAX)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_egress_notice_logged = False


@dataclass(frozen=True)
class _Target:
    """Everything a delivery needs, captured at commit time so a later settings
    change (or cache reset) cannot redirect a finding that is already queued."""

    url: str
    secret: str | None
    timeout: float


def _current_target() -> _Target | None:
    global _egress_notice_logged
    settings = get_settings()
    if not settings.webhook_url:
        return None
    if not settings.allow_egress:
        if not _egress_notice_logged:
            _egress_notice_logged = True
            log.info(
                "A finding webhook is configured (%s) but egress is disabled "
                "(AGENTFOX_ALLOW_EGRESS=false); nothing will be sent.",
                _display_url(settings.webhook_url),
            )
        return None
    return _Target(
        url=settings.webhook_url,
        secret=settings.webhook_secret or None,
        timeout=settings.webhook_timeout_seconds,
    )


def _display_url(url: str) -> str:
    """Scheme and host only — webhook URLs often embed a bearer token in the path."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else "<invalid url>"


# ---------------------------------------------------------------------------
# Session listeners
# ---------------------------------------------------------------------------


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, dt.datetime | dt.date) else value


def _finding_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Same field names as ``GET /api/findings/{id}``."""
    return {
        "id": data.get("id"),
        "type": data.get("type"),
        "severity": data.get("severity"),
        "status": data.get("status"),
        "title": data.get("title"),
        "subject_type": data.get("subject_type"),
        "subject_id": data.get("subject_id"),
        "controls": data.get("control_keys"),
        "evidence": data.get("evidence_json"),
        "occurrences": data.get("occurrences"),
        "last_seen_at": _iso(data.get("last_seen_at")),
        "suppression_reason": data.get("suppression_reason"),
        "suppressed_by": data.get("suppressed_by"),
        "resolution_note": data.get("resolution_note"),
        "resolved_by": data.get("resolved_by"),
        "resolved_at": _iso(data.get("resolved_at")),
        "created_at": _iso(data.get("created_at")),
    }


def _after_flush(session: Session, _flush_context: Any) -> None:
    try:
        if _current_target() is None:
            return
        events: list[tuple[Finding, str]] = [
            (obj, EVENT_FINDING_CREATED) for obj in session.new if isinstance(obj, Finding)
        ]
        for obj in session.dirty:
            if not isinstance(obj, Finding):
                continue
            # Attribute history is still pre-flush inside after_flush, so this is the
            # change this flush wrote — not whatever the object says by commit time.
            history = sa_inspect(obj).attrs.status.history
            if not history.added:
                continue
            after = history.added[0]
            if history.deleted:
                if history.deleted[0] == after:
                    continue
            elif after == "open":
                # The previous value was never loaded, so "reopened" cannot be told
                # apart from a no-op write; resolved/suppressed are news either way.
                continue
            event_name = _STATUS_EVENTS.get(str(after))
            if event_name:
                events.append((obj, event_name))
        if not events:
            return
        pending = session.info.setdefault(_INFO_KEY, [])
        for finding, event_name in events:
            # Snapshot now: with expire_on_commit=True the attributes would be gone
            # by after_commit, and loading them there would emit SQL.
            pending.append((finding, dict(sa_inspect(finding).dict), event_name))
    except Exception:  # never break a flush over a webhook
        log.warning("finding webhook: could not collect flushed findings", exc_info=True)


def _after_commit(session: Session) -> None:
    pending = session.info.pop(_INFO_KEY, None)
    if not pending:
        return
    try:
        target = _current_target()
        if target is None:
            return
        threshold = SEVERITY_RANK[get_settings().webhook_min_severity]
        sent: set[tuple[int, str]] = set()
        for finding, snapshot, event_name in pending:
            if (id(finding), event_name) in sent:
                continue
            state = sa_inspect(finding)
            # Rolled back inside a savepoint, deleted again, or detached by a close():
            # it is not in the database, so it is not news.
            if not state.persistent:
                continue
            data = {**snapshot, **state.dict}  # latest in-memory values, no lazy load
            if SEVERITY_RANK.get(str(data.get("severity", "")).lower(), 0) < threshold:
                continue
            if (
                event_name != EVENT_FINDING_CREATED
                and _STATUS_EVENTS.get(str(data.get("status"))) != event_name
            ):
                # Changed again before commit (resolved, then reopened in the same
                # transaction): only the status that was actually committed is news.
                continue
            sent.add((id(finding), event_name))
            _enqueue(
                target,
                {
                    "event": event_name,
                    "finding": _finding_payload(data),
                    "org_id": data.get("org_id"),
                },
            )
    except Exception:
        log.warning("finding webhook: could not queue committed findings", exc_info=True)


def _after_rollback(session: Session) -> None:
    # A savepoint rollback leaves the outer transaction alive, and the findings it
    # did not touch are still headed for commit — those it did touch are filtered
    # out at commit time as no longer persistent. Only a root rollback discards all.
    if not session.in_transaction():
        session.info.pop(_INFO_KEY, None)


def install(factory: sessionmaker[Session]) -> sessionmaker[Session]:
    """Wire finding webhooks into a session factory. Idempotent."""
    if getattr(factory, "_nometria_webhooks", False):
        return factory
    event.listen(factory, "after_flush", _after_flush)
    event.listen(factory, "after_commit", _after_commit)
    event.listen(factory, "after_rollback", _after_rollback)
    factory._nometria_webhooks = True  # type: ignore[attr-defined]
    return factory


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _ensure_worker() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="agentfox-webhooks", daemon=True)
            _worker.start()


def _run_worker() -> None:
    while True:
        target, body = _queue.get()
        try:
            _deliver(target, body)
        except Exception:  # pragma: no cover - _deliver already swallows
            log.warning("finding webhook: delivery crashed", exc_info=True)
        finally:
            _queue.task_done()


def _enqueue(target: _Target, body: dict[str, Any]) -> None:
    _ensure_worker()
    try:
        _queue.put_nowait((target, body))
    except queue.Full:
        log.warning(
            "finding webhook: queue full (%d); dropped %s for finding %s",
            _QUEUE_MAX,
            body.get("event"),
            (body.get("finding") or {}).get("id"),
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A signed body is for the configured host only; a redirect is a failure."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _deliver(target: _Target, body: dict[str, Any]) -> tuple[bool, str]:
    """POST one event, with one retry on 5xx / timeout / connection error."""
    if urlsplit(target.url).scheme not in ("http", "https"):
        detail = "webhook_url must be an http(s) URL"
        log.warning("finding webhook: %s", detail)
        return False, detail

    now = time.time()
    payload = {**body, "sent_at": dt.datetime.fromtimestamp(now, dt.UTC).isoformat()}
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"agentfox/{__version__}",
        "X-Nometria-Event": str(payload.get("event")),
        "X-Nometria-Delivery": uuid.uuid4().hex,
        "X-Nometria-Timestamp": str(int(now)),
    }
    if target.secret:
        digest = hmac.new(target.secret.encode(), raw, hashlib.sha256).hexdigest()
        headers["X-Nometria-Signature"] = f"sha256={digest}"

    detail = "not attempted"
    for attempt in (1, 2):
        request = urllib.request.Request(target.url, data=raw, headers=headers, method="POST")
        try:
            with _opener.open(request, timeout=target.timeout) as response:
                return True, f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            detail = f"HTTP {exc.code}"
            retryable = exc.code >= 500
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            detail = f"{type(reason).__name__}: {reason}"
            retryable = True
        if attempt == 1 and retryable:
            time.sleep(_RETRY_BACKOFF_SECONDS)
            continue
        break

    log.warning(
        "finding webhook: delivery of %s to %s failed: %s",
        payload.get("event"),
        _display_url(target.url),
        detail,
    )
    return False, detail


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def wait_for_delivery(timeout: float = 5.0) -> bool:
    """Block until every queued delivery has finished. True if the queue drained.

    For tests and for a process that wants to flush before exiting; the request path
    never calls this.
    """
    deadline = time.monotonic() + timeout
    with _queue.all_tasks_done:
        while _queue.unfinished_tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _queue.all_tasks_done.wait(remaining)
    return True


def send_test_event() -> tuple[bool, str]:
    """Synchronously send a ``webhook.test`` event to the configured URL.

    Returns ``(ok, detail)`` and never raises — intended for ``agentfox doctor`` or a
    CLI check.
    """
    try:
        settings = get_settings()
        if not settings.webhook_url:
            return False, "webhook_url is not set (AGENTFOX_WEBHOOK_URL)"
        if not settings.allow_egress:
            return False, "egress is disabled (AGENTFOX_ALLOW_EGRESS=false); nothing sent"
        target = _Target(
            url=settings.webhook_url,
            secret=settings.webhook_secret or None,
            timeout=settings.webhook_timeout_seconds,
        )
        return _deliver(target, {"event": EVENT_TEST, "finding": None, "org_id": settings.org_id})
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def reset_webhook_state() -> None:
    """Test hook: re-arm the once-only egress-disabled notice."""
    global _egress_notice_logged
    _egress_notice_logged = False
