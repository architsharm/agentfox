"""Monitors: create them, decide which are due, run them, turn what changed into findings.

A run has three steps, the same for every kind:

1. **Observe.** The kind's runner re-reads the source — downloads and rescans the
   repository, refetches the OpenAPI document, reads the MCP server's listing — and
   returns a snapshot.
2. **Diff.** The snapshot is compared with the one the previous run stored
   (`Monitor.baseline_json`). The first run only stores a baseline: monitoring reports
   *changes*, and everything already there was reported by the scan that created the
   monitor.
3. **Reconcile.** Each new condition is raised through `prove.findings.raise_finding`
   (subject ``monitor``, fingerprint = the condition's key), so a condition seen again
   is one finding, and one that comes back after being fixed reopens. Every open finding
   this monitor owns whose condition no longer holds is closed through
   `resolve_finding(..., automated=True)`.

A run that fails (GitHub down, spec unreachable, token revoked) never closes anything
and never replaces the baseline: "could not look" is not "nothing there". After
`monitor_failure_threshold` failures in a row it raises one `monitor_failing` finding,
closed by the next successful run.

A ``deployed_agent`` monitor's target is a `ProbeTarget` id: each run sends the live
probe library to that agent (`evaluation.live_probes.run_target`), so a probe that gets
through alerts like any other monitored change. Opting a target in creates it.

Findings opened, reopened and closed by a run reach the deployment's finding webhook
like any other finding (`core.webhooks`) and, when configured, Slack
(`monitoring.alerts`).

Extending: another kind registers a runner with :func:`register_kind`. A runner takes
``(session, monitor, ctx)`` and returns a :class:`RunOutcome`; the scheduling, failure
handling, finding reconciliation and alerts are shared.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from agentfox.capabilities.monitoring import alerts
from agentfox.capabilities.monitoring import snapshots as snap
from agentfox.core.config import get_settings
from agentfox.core.models import (
    Finding,
    Job,
    McpServer,
    McpToolSnapshot,
    Monitor,
    ProbeTarget,
    ScanRun,
    utcnow,
)
from agentfox.core.tenancy import session_org
from agentfox.core.vocab import AUTOMATION_ACTOR_TYPE
from agentfox.platform.ledger import chain
from agentfox.platform.ledger import findings as findings_mod

log = logging.getLogger(__name__)

JOB_KIND = "monitors.run"
ACTOR = "agentfox.monitoring"
SUBJECT_TYPE = "monitor"
HOUR = 3600
MIN_INTERVAL_SECONDS = 300
MAX_INTERVAL_SECONDS = 30 * 24 * HOUR

#: Run outcomes, as stored in `Monitor.status`.
PENDING, BASELINE, OK, CHANGED, FAILED, INCONCLUSIVE = (
    "pending",
    "baseline",
    "ok",
    "changed",
    "failed",
    "inconclusive",
)


class MonitorError(RuntimeError):
    """The source could not be read this time. Recorded on the monitor; never raised
    out of a run."""


@dataclass
class RunContext:
    now: dt.datetime
    #: schedule | push | manual
    trigger: str = "schedule"
    #: A specific ref or commit to read (a push delivers one); kind-specific.
    ref: str | None = None


@dataclass
class RunOutcome:
    """What a kind's runner hands back.

    ``snapshot`` replaces the baseline (``None`` keeps the old one). ``diff`` is what to
    reconcile (``None``: nothing to raise or close this time). ``touched`` lists findings
    the runner raised or closed itself through some other producer, as
    ``(finding, event)``, so they are alerted too.
    """

    snapshot: dict[str, Any] | None
    diff: snap.Diff | None
    summary: dict[str, Any] = field(default_factory=dict)
    status: str | None = None
    touched: list[tuple[Finding, str]] = field(default_factory=list)


Runner = Callable[[Session, Monitor, RunContext], RunOutcome]


@dataclass(frozen=True)
class KindSpec:
    kind: str
    runner: Runner
    default_interval: int
    description: str = ""


_KINDS: dict[str, KindSpec] = {}


def register_kind(
    kind: str, runner: Runner, *, default_interval: int = 6 * HOUR, description: str = ""
) -> None:
    """Teach monitoring a new kind of source. Idempotent per kind (last one wins)."""
    _KINDS[kind] = KindSpec(kind, runner, int(default_interval), description)


def kinds() -> dict[str, KindSpec]:
    return dict(_KINDS)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def _iso(value: dt.datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


def clamp_interval(seconds: int) -> int:
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, int(seconds)))


# ---------------------------------------------------------------------------
# Creating and reading monitors
# ---------------------------------------------------------------------------


def get_monitor(session: Session, kind: str, target: str) -> Monitor | None:
    return session.scalar(select(Monitor).where(Monitor.kind == kind, Monitor.target == target))


def ensure_monitor(
    session: Session,
    *,
    kind: str,
    target: str,
    name: str = "",
    config: dict[str, Any] | None = None,
    interval_seconds: int | None = None,
    baseline: dict[str, Any] | None = None,
    created_by: str = "",
    now: dt.datetime | None = None,
) -> tuple[Monitor, bool]:
    """Find or create the monitor for ``(kind, target)``. Returns ``(monitor, created)``.

    Called by the flows that connect a source. An existing monitor keeps what an operator
    chose (enabled, interval); its config is merged and, if it has no baseline yet, the
    one given is stored. A new monitor with a ``baseline`` is first due a full interval
    from now — the scan that created it just looked; without one it is due at once.
    """
    if kind not in _KINDS:
        raise ValueError(f"unknown monitor kind '{kind}'. Known: {', '.join(sorted(_KINDS))}")
    target = target.strip()
    if not target:
        raise ValueError("a monitor needs a target")
    now = now or utcnow()
    monitor = get_monitor(session, kind, target)
    if monitor is not None:
        if config:
            monitor.config_json = {**(monitor.config_json or {}), **config}
        if baseline and not monitor.baseline_json:
            monitor.baseline_json = baseline
            if monitor.status == PENDING:
                monitor.status = BASELINE
        session.flush()
        return monitor, False
    interval = clamp_interval(interval_seconds or _KINDS[kind].default_interval)
    monitor = Monitor(
        kind=kind,
        target=target,
        name=name or target,
        config_json=dict(config or {}),
        interval_seconds=interval,
        enabled=True,
        status=BASELINE if baseline else PENDING,
        baseline_json=dict(baseline or {}),
        next_run_at=now + dt.timedelta(seconds=interval) if baseline else None,
        last_result_json={},
        last_error="",
        consecutive_failures=0,
        created_by=created_by or ACTOR,
    )
    session.add(monitor)
    session.flush()
    chain.append(
        session,
        "monitor.created",
        actor_type="user" if created_by else AUTOMATION_ACTOR_TYPE,
        actor_id=created_by or ACTOR,
        subject_type=SUBJECT_TYPE,
        subject_id=monitor.id,
        payload={"kind": kind, "target": target, "interval_seconds": interval},
    )
    return monitor, True


def safe_ensure_monitor(session: Session, **kwargs: Any) -> Monitor | None:
    """`ensure_monitor` for the connect flows: a monitor that cannot be created must not
    fail the scan the person asked for. Runs in a savepoint and logs the failure."""
    try:
        with session.begin_nested():
            monitor, _created = ensure_monitor(session, **kwargs)
        return monitor
    except Exception:
        log.warning("could not create a monitor for %s", kwargs.get("target"), exc_info=True)
        return None


def monitor_json(monitor: Monitor) -> dict[str, Any]:
    return {
        "id": monitor.id,
        "kind": monitor.kind,
        "target": monitor.target,
        "name": monitor.name,
        "config": monitor.config_json or {},
        "interval_seconds": monitor.interval_seconds,
        "enabled": monitor.enabled,
        "status": monitor.status,
        "last_run_at": _iso(monitor.last_run_at),
        "next_run_at": _iso(monitor.next_run_at),
        "last_result": monitor.last_result_json or {},
        "last_error": monitor.last_error or "",
        "consecutive_failures": monitor.consecutive_failures,
        "has_baseline": bool(monitor.baseline_json),
        "created_by": monitor.created_by,
        "created_at": _iso(monitor.created_at),
    }


def is_due(monitor: Monitor, now: dt.datetime) -> bool:
    due_at = _aware(monitor.next_run_at)
    return bool(monitor.enabled) and (due_at is None or due_at <= now)


def due_monitors(
    session: Session, now: dt.datetime | None = None, limit: int | None = None
) -> list[Monitor]:
    """Enabled monitors whose `next_run_at` has passed, oldest first (never-run first)."""
    now = now or utcnow()
    query = (
        select(Monitor)
        .where(
            Monitor.enabled.is_(True),
            or_(Monitor.next_run_at.is_(None), Monitor.next_run_at <= now),
        )
        .order_by(Monitor.next_run_at.is_not(None), Monitor.next_run_at, Monitor.created_at)
    )
    if limit:
        query = query.limit(limit)
    return list(session.scalars(query))


def owned_findings(
    session: Session, monitor: Monitor, *, status: str | None = None
) -> list[Finding]:
    """Findings this monitor raised."""
    query = select(Finding).where(
        Finding.subject_type == SUBJECT_TYPE, Finding.subject_id == monitor.id
    )
    if status:
        query = query.where(Finding.status == status)
    return list(session.scalars(query.order_by(Finding.created_at.desc())))


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _finding_status(session: Session, monitor: Monitor, type_: str, key: str) -> str | None:
    fp = findings_mod.fingerprint(session_org(session), type_, SUBJECT_TYPE, monitor.id, (key,))
    return session.scalar(
        select(Finding.status)
        .where(Finding.fingerprint == fp)
        .order_by(Finding.created_at.desc())
        .limit(1)
    )


def _evidence(monitor: Monitor, extra: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        **extra,
        "condition_key": key,
        "monitor_id": monitor.id,
        "monitor_kind": monitor.kind,
        "target": monitor.target,
    }


def raise_condition(
    session: Session, monitor: Monitor, condition: snap.Condition
) -> tuple[Finding, str | None]:
    """Raise one condition as a finding on ``monitor``. Returns ``(finding, event)``
    where event is ``finding.created``, ``finding.reopened`` or None (already open)."""
    before = _finding_status(session, monitor, condition.type, condition.key)
    finding, created = findings_mod.raise_finding(
        session,
        type=condition.type,
        title=condition.title,
        severity=condition.severity,
        subject_type=SUBJECT_TYPE,
        subject_id=monitor.id,
        evidence=_evidence(monitor, condition.evidence, condition.key),
        control_keys=list(condition.control_keys),
        fingerprint_parts=(condition.key,),
    )
    if created:
        return finding, "finding.created"
    if before == findings_mod.RESOLVED and finding.status == findings_mod.OPEN:
        return finding, "finding.reopened"
    return finding, None


def reconcile(
    session: Session, monitor: Monitor, diff: snap.Diff
) -> tuple[list[tuple[Finding, str]], list[Finding]]:
    """Raise ``diff.new``; close this monitor's open findings of ``diff.managed_types``
    whose condition is not in ``diff.holding``. Returns ``(raised_with_event, closed)``."""
    raised: list[tuple[Finding, str]] = []
    for condition in diff.new:
        finding, event_name = raise_condition(session, monitor, condition)
        if event_name:
            raised.append((finding, event_name))
    closed: list[Finding] = []
    managed = set(diff.managed_types)
    for finding in owned_findings(session, monitor, status=findings_mod.OPEN):
        if finding.type not in managed:
            continue
        key = (finding.evidence_json or {}).get("condition_key")
        if key is None or (finding.type, key) in diff.holding:
            continue
        findings_mod.resolve_finding(
            session,
            finding,
            actor=ACTOR,
            note=f"the {monitor.kind} monitor for {monitor.target} no longer sees this",
            automated=True,
        )
        closed.append(finding)
    return raised, closed


def _record_failure(
    session: Session, monitor: Monitor, error: str, ctx: RunContext
) -> list[tuple[Finding, str]]:
    monitor.status = FAILED
    monitor.last_error = error[:2000]
    monitor.consecutive_failures = (monitor.consecutive_failures or 0) + 1
    monitor.last_result_json = {
        "trigger": ctx.trigger,
        "ref": ctx.ref,
        "error": error[:500],
        "at": ctx.now.isoformat(),
    }
    touched: list[tuple[Finding, str]] = []
    if monitor.consecutive_failures >= max(1, get_settings().monitor_failure_threshold):
        finding, event_name = raise_condition(
            session,
            monitor,
            snap.Condition(
                snap.MONITOR_FAILING,
                "failing",
                f"Monitor for {monitor.target} has failed {monitor.consecutive_failures} "
                "runs in a row",
                "medium",
                {"error": error[:500], "consecutive_failures": monitor.consecutive_failures},
            ),
        )
        if event_name:
            touched.append((finding, event_name))
    return touched


def run_monitor(
    session: Session,
    monitor: Monitor,
    *,
    now: dt.datetime | None = None,
    trigger: str = "schedule",
    ref: str | None = None,
) -> dict[str, Any]:
    """Run one monitor now, whatever its schedule. Never raises for a source failure.

    Returns the result stored on `Monitor.last_result_json`, plus ``monitor_id``.
    """
    now = now or utcnow()
    ctx = RunContext(now=now, trigger=trigger, ref=ref)
    spec = _KINDS.get(monitor.kind)
    monitor.last_run_at = now
    monitor.next_run_at = now + dt.timedelta(seconds=clamp_interval(monitor.interval_seconds))
    touched: list[tuple[Finding, str]] = []
    try:
        if spec is None:
            raise MonitorError(f"no runner for monitor kind '{monitor.kind}'")
        with session.begin_nested():
            outcome = spec.runner(session, monitor, ctx)
            raised: list[tuple[Finding, str]] = []
            closed: list[Finding] = []
            if outcome.diff is not None:
                raised, closed = reconcile(session, monitor, outcome.diff)
            session.flush()
    except Exception as exc:  # noqa: BLE001 - recorded on the monitor, not propagated
        error = str(exc) if isinstance(exc, MonitorError) else f"{type(exc).__name__}: {exc}"
        # Recorded on the monitor (and as a finding once it keeps failing), so INFO.
        log.info("monitor %s (%s %s) failed: %s", monitor.id, monitor.kind, monitor.target, error)
        touched = _record_failure(session, monitor, error, ctx)
        session.flush()
        for finding, event_name in touched:
            alerts.queue_finding_alert(session, finding, event_name, monitor)
        return {"monitor_id": monitor.id, **monitor.last_result_json, "status": FAILED}

    if outcome.snapshot is not None:
        monitor.baseline_json = outcome.snapshot
    failing = findings_mod.auto_resolve(
        session,
        type=snap.MONITOR_FAILING,
        subject_type=SUBJECT_TYPE,
        subject_id=monitor.id,
        fingerprint_parts=("failing",),
        note="the monitor ran successfully again",
        actor=ACTOR,
    )
    monitor.consecutive_failures = 0
    monitor.last_error = ""
    touched = list(outcome.touched) + raised + [(f, "finding.resolved") for f in closed]
    if failing is not None:
        touched.append((failing, "finding.resolved"))
    changed = bool(outcome.diff and outcome.diff.changed) or bool(raised or closed)
    status = outcome.status or (CHANGED if changed or outcome.touched else OK)
    monitor.status = status
    monitor.last_result_json = {
        "trigger": trigger,
        "ref": ref,
        "at": now.isoformat(),
        "status": status,
        "summary": outcome.summary,
        "changes": outcome.diff.changes if outcome.diff else {},
        "findings_opened": [f.id for f, e in raised if e == "finding.created"],
        "findings_reopened": [f.id for f, e in raised if e == "finding.reopened"],
        "findings_closed": [f.id for f in closed],
    }
    session.flush()
    if raised or closed:
        chain.append(
            session,
            "monitor.changed",
            actor_type=AUTOMATION_ACTOR_TYPE,
            actor_id=ACTOR,
            subject_type=SUBJECT_TYPE,
            subject_id=monitor.id,
            payload={
                "kind": monitor.kind,
                "target": monitor.target,
                "trigger": trigger,
                "opened": monitor.last_result_json["findings_opened"],
                "reopened": monitor.last_result_json["findings_reopened"],
                "closed": monitor.last_result_json["findings_closed"],
            },
        )
    for finding, event_name in touched:
        alerts.queue_finding_alert(session, finding, event_name, monitor)
    return {"monitor_id": monitor.id, **monitor.last_result_json}


def run_due(
    session: Session, *, now: dt.datetime | None = None, limit: int | None = None
) -> dict[str, Any]:
    """Run every due monitor in the session's tenant, up to ``limit``
    (`settings.monitor_batch_limit`). The rest stay due for the next call."""
    now = now or utcnow()
    limit = limit or max(1, get_settings().monitor_batch_limit)
    batch = due_monitors(session, now, limit)
    results = [run_monitor(session, m, now=now) for m in batch]
    remaining = (
        session.scalar(
            select(func.count())
            .select_from(Monitor)
            .where(
                Monitor.enabled.is_(True),
                or_(Monitor.next_run_at.is_(None), Monitor.next_run_at <= now),
            )
        )
        or 0
    )
    return {
        "ran": len(results),
        "failed": sum(1 for r in results if r.get("status") == FAILED),
        "changed": sum(1 for r in results if r.get("status") == CHANGED),
        "remaining_due": remaining,
        "results": results,
    }


def handle_job(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """The `monitors.run` job: one named monitor (``monitor_id``), or every due one."""
    monitor_id = payload.get("monitor_id")
    if monitor_id:
        monitor = session.get(Monitor, monitor_id)
        if monitor is None:
            return {"ran": 0, "skipped": f"no monitor '{monitor_id}'"}
        if not monitor.enabled and not payload.get("force"):
            return {"ran": 0, "skipped": "monitor is paused"}
        result = run_monitor(
            session,
            monitor,
            trigger=str(payload.get("trigger") or "manual"),
            ref=payload.get("ref") or None,
        )
        return {"ran": 1, "results": [result]}
    return run_due(session, limit=payload.get("limit"))


def request_run(
    session: Session,
    monitor: Monitor,
    *,
    trigger: str,
    ref: str | None = None,
    requested_by: str = "",
) -> Job:
    """Queue an immediate run of ``monitor`` (a push, a person pressing "run").

    A run already queued for the same monitor is reused (its ref updated) rather than
    duplicated: ten pushes in a minute are one rescan of the latest commit.
    """
    from agentfox.platform.jobs import store as jobs_db

    # This package owns the `monitors.run` kind, so it registers it rather than
    # relying on whichever app wired the job handlers having been imported.
    jobs_db.register(JOB_KIND, handle_job)

    monitor.next_run_at = utcnow()
    for job in session.scalars(select(Job).where(Job.kind == JOB_KIND, Job.status == "pending")):
        if (job.payload_json or {}).get("monitor_id") == monitor.id:
            job.payload_json = {**job.payload_json, "ref": ref, "trigger": trigger}
            session.flush()
            return job
    return jobs_db.enqueue(
        session,
        JOB_KIND,
        {"monitor_id": monitor.id, "ref": ref, "trigger": trigger},
        org_id=session_org(session),
        requested_by=requested_by or f"monitor:{trigger}",
    )


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------


def _run_github_repo(session: Session, monitor: Monitor, ctx: RunContext) -> RunOutcome:
    from agentfox.capabilities.discovery.repo import scan as discovery_scan
    from agentfox.capabilities.monitoring import github as gh
    from agentfox.core.crypto import decrypt_secret

    config = monitor.config_json or {}
    conn = gh.connection(session, config.get("connection_id"))
    if conn is None:
        raise MonitorError("no GitHub account is connected for this tenant")
    try:
        token = decrypt_secret(conn.access_token_encrypted)
    except Exception as exc:
        raise MonitorError(f"the stored GitHub token cannot be used: {exc}") from exc
    ref = ctx.ref or config.get("ref") or ""
    run = ScanRun(
        connection_id=conn.id,
        repo_full_name=monitor.target,
        ref=ref,
        status="running",
    )
    session.add(run)
    session.flush()
    with tempfile.TemporaryDirectory(prefix="agentfox-monitor-") as tmp:
        try:
            root = gh.download_and_extract(monitor.target, ref, token, Path(tmp))
        except gh.RepoFetchError as exc:
            raise MonitorError(str(exc)) from exc
        report = discovery_scan(root)
    current = snap.repo_snapshot(report)
    summary = snap.summarise(current)
    run.status = "completed"
    run.completed_at = utcnow()
    run.summary_json = {
        "files_scanned": report.files_scanned,
        "code_files_scanned": report.code_files_scanned,
        "inconclusive": report.inconclusive,
        "frameworks": report.frameworks,
        "sites": report.by_kind(),
        "trigger": f"monitor:{ctx.trigger}",
        "monitor_id": monitor.id,
    }
    summary["scan_run_id"] = run.id
    previous = monitor.baseline_json or {}
    if report.inconclusive:
        # Read nothing it understands: keep the baseline, close nothing.
        return RunOutcome(None, None, summary, status=INCONCLUSIVE)
    if not previous:
        return RunOutcome(current, None, summary, status=BASELINE)
    return RunOutcome(current, snap.diff_repo(previous, current, label=monitor.target), summary)


def _run_hosted_api(session: Session, monitor: Monitor, ctx: RunContext) -> RunOutcome:
    from agentfox.capabilities.discovery.openapi import SpecFetchError, fetch_spec

    try:
        spec = fetch_spec(monitor.target)
    except SpecFetchError as exc:
        raise MonitorError(str(exc)) from exc
    if not isinstance(spec, dict):
        raise MonitorError("the document is not an OpenAPI object")
    current = snap.api_snapshot(spec)
    summary = snap.summarise(current)
    previous = monitor.baseline_json or {}
    if not current["operations"] and previous.get("operations"):
        # An empty document where there were operations is far likelier a broken
        # deploy of the docs than an API that removed every endpoint.
        return RunOutcome(None, None, summary, status=INCONCLUSIVE)
    if not previous:
        return RunOutcome(current, None, summary, status=BASELINE)
    label = (monitor.config_json or {}).get("endpoint_url") or monitor.name or monitor.target
    return RunOutcome(current, snap.diff_api(previous, current, label=label), summary)


def tools_digest(tools: list[dict[str, Any]]) -> str:
    """The digest `registry.service.scan_mcp_server` stores for a listing."""
    payload = json.dumps(tools, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _run_mcp_server(session: Session, monitor: Monitor, ctx: RunContext) -> RunOutcome:
    from agentfox.capabilities.monitoring import mcp_live
    from agentfox.platform.registry.service import scan_mcp_server

    config = monitor.config_json or {}
    server = None
    if config.get("mcp_server_id"):
        server = session.get(McpServer, config["mcp_server_id"])
    if server is None:
        server = session.scalar(select(McpServer).where(McpServer.name == monitor.target))
    if server is None:
        raise MonitorError(f"no MCP server named '{monitor.target}' is registered any more")
    latest = session.scalars(
        select(McpToolSnapshot)
        .where(McpToolSnapshot.mcp_server_id == server.id)
        .order_by(McpToolSnapshot.captured_at.desc())
    ).first()
    previous_digest = (monitor.baseline_json or {}).get("digest")

    if not mcp_live.can_fetch(server.url or "", server.transport or ""):
        # A stdio (or SSE) server is never started; its listing is pushed. Report whether
        # the pushed listing changed since the last run — the drift finding itself was
        # raised when the listing arrived.
        digest = latest.digest if latest is not None else None
        summary = {
            "live": False,
            "transport": server.transport,
            "tools": len(latest.tools_json or []) if latest is not None else 0,
            "digest": digest,
            "note": "listing is pushed, not fetched: "
            f"agentfox scan mcp {server.name} --file tools.json",
        }
        snapshot = {"type": "mcp", "digest": digest, "live": False}
        changed = bool(previous_digest and digest and previous_digest != digest)
        status = BASELINE if not monitor.baseline_json else (CHANGED if changed else OK)
        return RunOutcome(snapshot, None, summary, status=status)

    try:
        tools = mcp_live.fetch_tools(server.url)
    except mcp_live.McpListingError as exc:
        raise MonitorError(str(exc)) from exc
    digest = tools_digest(tools)
    touched: list[tuple[Finding, str]] = []
    issues: list[dict[str, Any]] = []
    if latest is None or latest.digest != digest:
        before = {
            f.id: f.status
            for f in session.scalars(
                select(Finding).where(
                    Finding.subject_type == "mcp_server", Finding.subject_id == server.id
                )
            )
        }
        result = scan_mcp_server(session, server, tools)
        issues = result["issues"]
        for finding in session.scalars(
            select(Finding).where(
                Finding.subject_type == "mcp_server", Finding.subject_id == server.id
            )
        ):
            was = before.get(finding.id)
            if was is None:
                touched.append((finding, "finding.created"))
            elif was != finding.status and finding.status == findings_mod.OPEN:
                touched.append((finding, "finding.reopened"))
            elif was != finding.status and finding.status == findings_mod.RESOLVED:
                touched.append((finding, "finding.resolved"))
    else:
        server.last_scanned_at = ctx.now
    summary = {
        "live": True,
        "tools": len(tools),
        "digest": digest,
        "drifted": latest is not None and latest.digest != digest,
        "issues": [i.get("type") for i in issues],
    }
    snapshot = {
        "type": "mcp",
        "digest": digest,
        "live": True,
        "tools": sorted(str(t.get("name")) for t in tools),
    }
    if not monitor.baseline_json:
        status: str | None = BASELINE
    else:
        status = CHANGED if summary["drifted"] else None
    return RunOutcome(snapshot, None, summary, status=status, touched=touched)


#: How a deployed_agent run waits between probes. A module attribute so tests can
#: replace it; looked up at call time.
def _probe_sleep(seconds: float) -> None:
    time.sleep(seconds)


def _run_deployed_agent(session: Session, monitor: Monitor, ctx: RunContext) -> RunOutcome:
    """Send the live probe library to an opted-in probe target (`ProbeTarget` id).

    The `probes.run` job can probe the same target, so both go through one clock: the
    target's own ``next_due_at``, which every run moves at least
    `live_probes.MIN_INTERVAL_SECONDS` ahead. A scheduled run before it is due sends
    nothing; a manual one is held to `live_probes.MIN_MANUAL_GAP_SECONDS`, as the
    "run now" route is. The monitor's own next run is moved to the target's.
    """
    from agentfox.capabilities.evaluation import live_probes

    target_id = (monitor.config_json or {}).get("probe_target_id") or monitor.target
    target = session.get(ProbeTarget, target_id)
    if target is None:
        raise MonitorError(f"no probe target '{target_id}' exists any more")
    if not get_settings().live_probes_enabled:
        return RunOutcome(
            None,
            None,
            {"skipped": "live probes are disabled on this deployment"},
            status=INCONCLUSIVE,
        )
    if not target.enabled or not target.opted_in_by:
        return RunOutcome(
            None, None, {"skipped": "the probe target is not opted in"}, status=INCONCLUSIVE
        )

    now = _aware(ctx.now) or utcnow()
    if ctx.trigger == "manual":
        last = _aware(target.last_run_at)
        gate = last + dt.timedelta(seconds=live_probes.MIN_MANUAL_GAP_SECONDS) if last else None
    else:
        gate = _aware(target.next_due_at)
    if gate is not None and now < gate:
        if ctx.trigger != "manual":
            monitor.next_run_at = gate
        return RunOutcome(
            None,
            None,
            {"skipped": "probed recently; not due yet", "next_due_at": gate.isoformat()},
            status=monitor.status if monitor.status != PENDING else BASELINE,
        )

    campaign = live_probes.run_target(
        session,
        target,
        now=now,
        sleep=_probe_sleep,
        actor_type=AUTOMATION_ACTOR_TYPE,
        actor_id=ACTOR,
    )
    if target.next_due_at is not None:
        monitor.next_run_at = target.next_due_at
    summary = dict(campaign.summary_json or {})
    found = summary.get("findings") or {}
    touched: list[tuple[Finding, str]] = []
    for finding_id in found.get("opened") or []:
        finding = session.get(Finding, finding_id)
        if finding is not None:
            recurred = (finding.evidence_json or {}).get(findings_mod.RECURRENCES_KEY)
            touched.append((finding, "finding.reopened" if recurred else "finding.created"))
    for finding_id in found.get("closed") or []:
        finding = session.get(Finding, finding_id)
        if finding is not None:
            touched.append((finding, "finding.resolved"))
    result = {
        "campaign_id": campaign.id,
        "agent": target.agent_slug,
        "attacks_attempted": summary.get("attacks_attempted"),
        "contained": summary.get("contained"),
        "escaped": summary.get("escaped"),
        "errors": summary.get("errors"),
        "direction": (summary.get("posture") or {}).get("direction"),
        "headline": summary.get("headline"),
        "findings": found,
    }
    snapshot = {"type": "deployed_agent", "campaign_id": campaign.id}
    status = BASELINE if not monitor.baseline_json and not touched else None
    return RunOutcome(snapshot, None, result, status=status, touched=touched)


register_kind(
    "github_repo",
    _run_github_repo,
    default_interval=6 * HOUR,
    description="re-download and rescan a connected GitHub repository",
)
register_kind(
    "hosted_api",
    _run_hosted_api,
    default_interval=6 * HOUR,
    description="refetch a hosted API's OpenAPI document and diff its operations",
)
register_kind(
    "mcp_server",
    _run_mcp_server,
    default_interval=HOUR,
    description="read a remote MCP server's tool listing and check it for drift",
)
register_kind(
    "deployed_agent",
    _run_deployed_agent,
    default_interval=24 * HOUR,
    description="send the live probe library to an opted-in deployed agent",
)
