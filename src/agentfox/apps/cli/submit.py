"""Optional, explicit submission of a local scan's redacted summary to a running
control plane, from `agentfox scan --submit` / `agentfox scan --sessions --submit`.

Nothing here ever runs unless a human opts in — no flag and no confirmed prompt means
this module is never imported for anything but its exceptions. What gets sent is
exactly `ScanReport.to_submission_payload()`: no file contents, no line numbers, no
source snippets, no full file paths. See that method's docstring for the precise
contract this is not allowed to loosen.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx
from rich.console import Console

from agentfox.capabilities.discovery.repo import ScanReport


class SubmissionUnavailable(Exception):
    """No control plane reachable or configured. Never a reason to fail the scan
    itself — the caller always has a complete local result regardless."""


def submit_scan_report(report: ScanReport, *, source: str) -> dict[str, Any]:
    """POST the redacted summary of `report` to `AGENTFOX_API_URL`.

    Raises `SubmissionUnavailable` on anything that stops the submission — no URL
    configured, no credential configured, the request itself failing — so callers can
    show one friendly message rather than a traceback.
    """
    base = os.environ.get("AGENTFOX_API_URL") or os.environ.get("NOMETRIA_API_URL")
    if not base:
        raise SubmissionUnavailable(
            "AGENTFOX_API_URL is not set — point it at a running `agentfox serve` "
            "(yours or your team's) to submit."
        )

    # AGENTFOX_ first, NOMETRIA_ as the legacy alias — the same precedence
    # config.py applies to every other setting (ENV_PREFIX / LEGACY_ENV_PREFIX).
    # This module read the environment directly and so never picked up the
    # rename, which meant the product told operators to set a variable named
    # after the old company and the new one silently did nothing.
    token = os.environ.get("AGENTFOX_API_TOKEN") or os.environ.get("NOMETRIA_API_TOKEN")
    dev_user = os.environ.get("AGENTFOX_USER") or os.environ.get("NOMETRIA_USER")
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif dev_user:
        headers["X-Nometria-User"] = dev_user
    else:
        raise SubmissionUnavailable(
            "no credentials configured — set AGENTFOX_API_TOKEN (`agentfox admin auth issue "
            "<email>` on that deployment) or AGENTFOX_USER for a dev deployment."
        )

    payload = report.to_submission_payload(source=source)
    try:
        response = httpx.post(
            f"{base.rstrip('/')}/api/discovery/submit",
            json=payload,
            headers=headers,
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SubmissionUnavailable(f"could not reach {base}: {exc}") from exc
    return response.json()


_PITCH = (
    "Want a fuller report? Submitting shares only structure and semantics — file and "
    "finding counts, detected frameworks, and which top-level folder each finding is "
    "in — never file contents, code, or other business data. It also unlocks "
    "capabilities a one-off local scan can't give you: draft agent registration, "
    "proposed guardrail policies, and coverage tracking over time in the dashboard."
)


def maybe_submit_report(
    report: ScanReport,
    *,
    source: str,
    explicit: bool | None,
    console: Console,
) -> None:
    """Handle the optional submit step for a CLI scan command.

    `explicit=True`/`False` come from `--submit`/`--no-submit` and are followed
    unconditionally. `explicit=None` means neither flag was passed: ask interactively,
    but only when stdout is a real terminal — an unattended or piped run never submits
    and never blocks on input. Default is always "no" either way.
    """
    if explicit is False:
        return
    if explicit is None:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return
        console.print(f"\n[dim]{_PITCH}[/]")
        import typer

        if not typer.confirm("Submit to the dashboard?", default=False):
            return

    try:
        result = submit_scan_report(report, source=source)
    except SubmissionUnavailable as exc:
        console.print(f"[yellow]Could not submit: {exc}[/]")
        return

    summary = result.get("summary", {})
    console.print(
        f"[green]Submitted.[/] scan [bold]{result.get('scan_run_id')}[/] — "
        f"{len(summary.get('agents_proposed', []))} draft agent(s), "
        f"{len(summary.get('policies_proposed', []))} proposed polic(ies) — "
        "review them in the dashboard."
    )
