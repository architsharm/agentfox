"""Regressions for known CLI defects — one test (or small group) per fix.

Each test names the behaviour that was wrong, so a future failure reads as "this came
back", not as an unexplained assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()
REPO = Path(__file__).resolve().parents[3]

REFUND_POLICY = (
    "Refunds under $10 are auto-approved. Refunds between $10 and $100 must run a "
    "fraud check before proceeding, and refunds over $100 require approval from the "
    "finance team.\n"
)


def flat(output: str) -> str:
    return " ".join(output.split())


def _json(output: str):
    """Parse JSON output, ignoring Alembic's stamp log lines on a first-run database."""
    lines = [line for line in output.splitlines() if not line.startswith("INFO")]
    return json.loads("\n".join(lines))


def _seed() -> dict:
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        return seed(session)


def _policy_mode(key: str) -> str | None:
    from agentfox.apps.cli.demo import _current_mode

    return _current_mode(key)


# ---------------------------------------------------------------------------
# 1. init tells the truth about each pack, and writes the real defaults
# ---------------------------------------------------------------------------


def test_compliance_status_verbose_honours_the_framework():
    from agentfox_ee.compliance import controls_for_framework, latest_statuses

    from agentfox.capabilities.compliance.catalog import load_catalog
    from agentfox.core.db import session_scope

    _seed()
    assert runner.invoke(app, ["admin", "catalog", "compute"]).exit_code == 0

    with session_scope() as session:
        computed = set(latest_statuses(session))
        for framework in load_catalog()["frameworks"]:
            mapped = {c["key"] for c in controls_for_framework(session, framework)}
            inside, outside = computed & mapped, computed - mapped
            if inside and outside:
                break
        else:  # pragma: no cover - catalog shape guard
            pytest.skip("no framework maps a strict subset of controls")

    result = runner.invoke(app, ["report", "status", "--framework", framework, "--verbose"])
    assert result.exit_code == 0, result.output
    for key in inside:
        assert key in result.output
    for key in outside:
        assert key not in result.output
