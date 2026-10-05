"""Work that must not run inside the request.

Evidence packaging, red-team sweeps and compliance recomputation all run synchronously
today, which puts a multi-second job on the path of a call that is supposed to add
milliseconds. The obvious cost is latency. The one that matters is different: when the
governance layer is slow, teams raise its timeout, and a timeout raised far enough is a
control that fails open on every busy afternoon.

So the split is not an optimisation, it is what keeps the inline path inline.

One property distinguishes this from a task queue. A dropped job here is a missing
piece of evidence, and evidence that is missing without a record is worse than evidence
that was never collected — the gap looks identical to "nothing happened". So a job that
exhausts its retries is **dead-lettered, never discarded**, and the dead letter is part
of the queue's public state rather than a log line.

Deliberately small and in-process. The interface is what matters — enqueue, run, retry,
dead-letter, inspect — and a Redis or SQS implementation belongs behind it. Building
that now would be committing to infrastructure before anyone has run this at a scale
that needs it.
"""

from __future__ import annotations

import datetime as dt
import logging
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

PENDING = "pending"
RUNNING = "running"
DONE = "done"
DEAD = "dead"


@dataclass
class Job:
    """One unit of deferred work."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    max_attempts: int = 3
    attempts: int = 0
    status: str = PENDING
    last_error: str = ""
    enqueued_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    #: Carried so a job can be attributed to the tenant whose request created it.
    org_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "last_error": self.last_error,
            "org_id": self.org_id,
            "enqueued_at": self.enqueued_at.isoformat() if self.enqueued_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class JobQueue:
    """In-process queue with retries and a dead-letter that nobody can lose.

    ``run_pending`` is explicit rather than a background thread. A worker that starts
    itself makes the request path's behaviour depend on whether anything else in the
    process happened to import this module, and the whole point here is to know exactly
    what runs where.
    """

    def __init__(self) -> None:
        self._pending: deque[Job] = deque()
        self._dead: list[Job] = []
        self._done: list[Job] = []
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(self, kind: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._handlers[kind] = handler

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        max_attempts: int = 3,
        org_id: str | None = None,
        now: dt.datetime | None = None,
    ) -> Job:
        """Accept work for later.

        A kind with no handler is refused here rather than at run time. Discovering
        that nothing knows how to package evidence, an hour after the request that
        needed it, is the failure this whole module exists to avoid.
        """
        if kind not in self._handlers:
            raise KeyError(
                f"no handler registered for '{kind}'. Refusing to accept work that "
                "nothing knows how to do — the failure would surface an hour later as "
                "missing evidence"
            )
        job = Job(
            kind=kind,
            payload=payload or {},
            max_attempts=max_attempts,
            org_id=org_id,
            enqueued_at=now or dt.datetime.now(dt.UTC),
        )
        self._pending.append(job)
        return job

    def run_pending(self, *, limit: int | None = None, now: dt.datetime | None = None) -> int:
        """Run queued work. Returns how many jobs reached a terminal state."""
        now = now or dt.datetime.now(dt.UTC)
        finished = 0
        budget = limit if limit is not None else len(self._pending)
        for _ in range(budget):
            if not self._pending:
                break
            job = self._pending.popleft()
            job.status = RUNNING
            job.attempts += 1
            try:
                self._handlers[job.kind](job.payload)
            except Exception as exc:
                job.last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "job '%s' attempt %d failed: %s", job.kind, job.attempts, job.last_error
                )
                log.debug("%s", traceback.format_exc())
                if job.attempts >= job.max_attempts:
                    # Never discarded. Evidence that is missing without a record is
                    # worse than evidence never collected — the gap looks identical to
                    # "nothing happened".
                    job.status = DEAD
                    job.finished_at = now
                    self._dead.append(job)
                    finished += 1
                else:
                    job.status = PENDING
                    self._pending.append(job)
                continue
            job.status = DONE
            job.finished_at = now
            self._done.append(job)
            finished += 1
        return finished

    def retry_dead(self, kind: str | None = None) -> int:
        """Put dead-lettered work back, once whatever broke has been fixed."""
        revived = [j for j in self._dead if kind is None or j.kind == kind]
        for job in revived:
            self._dead.remove(job)
            job.status = PENDING
            job.attempts = 0
            job.last_error = ""
            self._pending.append(job)
        return len(revived)

    @property
    def pending(self) -> int:
        return len(self._pending)

    @property
    def dead_letter(self) -> list[Job]:
        return list(self._dead)

    def stats(self) -> dict[str, Any]:
        return {
            "pending": len(self._pending),
            "done": len(self._done),
            "dead": len(self._dead),
            "dead_kinds": sorted({j.kind for j in self._dead}),
            "handlers": sorted(self._handlers),
        }


#: Work that belongs off the request path. Named rather than discovered so that adding
#: a slow step to the inline path is a visible decision.
DEFERRABLE = (
    "evidence.package",
    "redteam.sweep",
    "compliance.recompute",
    "eval.run",
    "retrieval.baseline",
)
