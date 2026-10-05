"""Local-scan submission — the optional third path out of `agentfox scan` and
`agentfox scan --sessions`, next to plain terminal output and `--json`.

Both commands run `discovery.py`'s static scanner entirely on the developer's own
machine, and by default nothing about the result leaves it. This endpoint is what
`--submit` (or the interactive prompt either command offers at the end of a run)
talks to when a human explicitly opts in — the CLI never calls it unless asked to.

What it receives is deliberately narrow: `discovery.ScanReport.to_submission_payload()`
is the only shape the CLI is willing to build, and it carries counts, detected
frameworks, and — per finding — only a top-level directory name, never a file's full
path, its line number, or any literal source text. This route trusts that shape and
does not attempt to recover anything richer from it.

A submission is treated exactly like a GitHub-connected repo scan once it arrives:
one `ScanRun`, plus the same draft-agent/proposed-policy review flow
(`registry.service.propose_from_scan`), so a scan looks the same in the dashboard
whichever door it came through.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agentfox.core.models import ScanRun, User, utcnow
from agentfox.gateway.deps import db, require
from agentfox.prove.audit import chain
from agentfox.registry.service import propose_from_scan

router = APIRouter(tags=["discovery"])


class SubmittedSite(BaseModel):
    kind: str
    top_dir: str
    provider: str | None = None


class ScanSubmission(BaseModel):
    source: str  # "quickscan" | "check"
    label: str = "repo"
    files_scanned: int = 0
    frameworks: list[str] = []
    coverage: float | None = None
    counts: dict[str, int] = {}
    sites: list[SubmittedSite] = []


@router.post("/api/discovery/submit", summary="Submit a redacted local scan for review")
def submit_scan(
    payload: ScanSubmission,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    run = ScanRun(
        source_kind="cli",
        repo_full_name=payload.label,
        status="completed",
        completed_at=utcnow(),
    )
    session.add(run)
    session.flush()

    created_agents, created_policies = propose_from_scan(
        session,
        run_id=run.id,
        repo_slug_base=payload.label,
        repo_display_name=payload.label,
        frameworks=payload.frameworks,
        sites=[s.model_dump() for s in payload.sites],
        author=user.email or user.id,
    )

    run.summary_json = {
        "cli_command": payload.source,
        "files_scanned": payload.files_scanned,
        "frameworks": payload.frameworks,
        "coverage": payload.coverage,
        "sites": payload.counts,
        "agents_proposed": created_agents,
        "policies_proposed": created_policies,
    }
    session.flush()

    chain.append(
        session,
        "integration.cli.scanned",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="scan_run",
        subject_id=run.id,
        payload=run.summary_json,
    )
    session.commit()
    return {"scan_run_id": run.id, "status": run.status, "summary": run.summary_json}
