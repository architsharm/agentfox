"""The attack test's guard checks on self-hosted SQLite (wow3 ui B3).

8 of 67 checks failed with ``database is locked`` (a 500) while the runner reported
results at the same time. A dry run opens a savepoint, which on SQLite starts a
deferred transaction: it reads (taking a snapshot), then writes inside the
savepoint. If another connection committed in between, SQLite can't upgrade the
stale snapshot to a writer and fails at once, without waiting out the busy timeout.
The check now takes the write lock first (``BEGIN IMMEDIATE``), so it waits its turn.
"""

from __future__ import annotations

import threading

from sqlalchemy import text

from agentfox.core.db import get_sessionmaker, sqlite_write_lock


def _table(session):
    session.execute(text("CREATE TABLE IF NOT EXISTS lock_probe (n INTEGER)"))
    session.commit()


def _race(take_lock_first: bool) -> Exception | None:
    """A reads in a savepoint, B writes and commits, A writes: the dry run's shape."""
    make = get_sessionmaker()
    a, b = make(), make()
    _table(a)
    error: Exception | None = None
    try:
        if take_lock_first:
            sqlite_write_lock(a)
        nested = a.begin_nested()
        a.execute(text("SELECT count(*) FROM lock_probe")).scalar()

        def other_writer():
            b.execute(text("INSERT INTO lock_probe VALUES (1)"))
            b.commit()

        writer = threading.Thread(target=other_writer)
        writer.start()
        writer.join(timeout=0.5)  # with the lock held first, B waits for A
        try:
            a.execute(text("INSERT INTO lock_probe VALUES (2)"))
        except Exception as exc:  # noqa: BLE001 - the failure under test
            error = exc
        nested.rollback()
        a.commit()
        writer.join(timeout=30)
    finally:
        a.close()
        b.close()
    return error


def test_a_dry_run_that_reads_first_loses_the_race_without_the_lock():
    err = _race(take_lock_first=False)
    assert err is not None and "database is locked" in str(err)


def test_taking_the_write_lock_first_waits_instead_of_failing():
    assert _race(take_lock_first=True) is None


def test_a_failed_check_names_its_cause_not_the_network():
    from agentfox.capabilities.onboarding import runner, service

    def said(why: str) -> str:
        error = f"{runner.GUARD_ERROR_PREFIX} ({why})"
        return service.errored_summary([{"id": "j", "outcome": "errored", "error": error}]) or ""

    locked = said("agentfox.ApiError: 503: AgentFox's database was busy (database is locked)")
    assert "database was busy" in locked and "Postgres" in locked
    assert "reachable" not in locked
    failed = said("agentfox.ApiError: 500: Internal Server Error")
    assert "server failed while checking them (HTTP 500" in failed and "reachable" not in failed
    down = said("httpx.ConnectError: [Errno 61] Connection refused")
    assert "couldn't reach its server" in down


def test_the_runner_tries_a_busy_check_again(monkeypatch):
    from agentfox.capabilities.onboarding import client

    monkeypatch.setattr(client, "GUARD_RETRIES", (0, 0, 0))
    answers = [client.ApiError(503, "busy"), client.ApiError(503, "busy"), {"verdict": "allow"}]

    def send():
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    assert client._retrying(send) == {"verdict": "allow"}
    # A refusal that won't change is not retried.
    calls = []

    def refused():
        calls.append(1)
        raise client.ApiError(403, "no")

    try:
        client._retrying(refused)
    except client.ApiError:
        pass
    assert calls == [1]
