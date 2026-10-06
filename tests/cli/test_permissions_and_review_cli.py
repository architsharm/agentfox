"""Declaring what a tool may do, and moving a compliance mapping out of DRAFT.

Two gaps these cover, both of which were "the workflow exists, the entry point doesn't":

* Containment is *declared*, not detected, but there was no CLI to declare a tool's impact
  at all — so the control that holds when a detector misses was unreachable without the API.
* Every framework mapping ships `DRAFT — UNVERIFIED / NOT LEGAL ADVICE`, and a reviewer had
  nothing reviewable to work from.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from agentfox.cli.main import app

runner = CliRunner()


def test_declaring_a_tool_records_its_impact(isolated_db):
    result = runner.invoke(
        app,
        [
            "declare",
            "tool",
            "payments.wire",
            "--impact",
            "irreversible",
            "--triggers",
            "ledger.write",
        ],
    )
    assert result.exit_code == 0, result.output
    listed = runner.invoke(app, ["declare", "list", "tools", "--json"])
    assert listed.exit_code == 0
    rows = json.loads(listed.output)
    row = next(r for r in rows if r["key"] == "payments.wire")
    assert row["impact"] == "irreversible"
    assert row["triggers"] == ["ledger.write"]


def test_an_invalid_impact_is_refused_rather_than_stored(isolated_db):
    result = runner.invoke(app, ["declare", "tool", "x.y", "--impact", "sort-of-dangerous"])
    assert result.exit_code == 2
    assert "impact must be one of" in result.output


def test_doctor_reports_containment_readiness_not_just_detectors(isolated_db):
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.output)
    checks = {row["check"]: row for row in payload}
    assert "containment" in checks, checks.keys()
    # Nothing declared yet, and no traffic: a starting state, not a misconfiguration.
    assert checks["containment"]["state"] == "warn"
    assert "data scope" in checks

    runner.invoke(app, ["declare", "tool", "payments.wire", "--impact", "irreversible"])
    after = json.loads(runner.invoke(app, ["doctor", "--json"]).output)
    containment = next(row for row in after if row["check"] == "containment")
    assert "can act" in containment["detail"] or "no capability grants" in containment["detail"]


def test_a_reviewer_packet_lists_every_mapping_awaiting_review(isolated_db, tmp_path):
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    out = tmp_path / "packet.md"
    result = runner.invoke(
        app, ["report", "review-packet", "--framework", "eu-ai-act", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    document = out.read_text()
    assert "Compliance mapping review packet — eu-ai-act" in document
    assert "awaiting review" in document
    assert "Clause claimed" in document


def test_an_unknown_framework_is_refused(isolated_db, tmp_path):
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(app, ["report", "review-packet", "--framework", "not-a-framework"])
    assert result.exit_code == 1
    assert "unknown framework" in result.output


def test_sign_off_moves_a_mapping_out_of_draft_and_names_the_reviewer(isolated_db, tmp_path):
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(
        app,
        [
            "report",
            "signoff",
            "NOM-IAM-03",
            "--framework",
            "eu-ai-act",
            "--reviewer",
            "A. Counsel",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "reviewed" in result.output and "A. Counsel" in result.output

    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.core.models import FrameworkMapping

    with session_scope() as session:
        mappings = list(
            session.scalars(
                select(FrameworkMapping).where(
                    FrameworkMapping.control_key == "NOM-IAM-03",
                    FrameworkMapping.framework == "eu-ai-act",
                )
            )
        )
    assert mappings and all(m.review_status == "reviewed" for m in mappings)
    assert all(m.reviewed_by == "A. Counsel" for m in mappings)


def test_signing_off_something_that_does_not_exist_fails_loudly(isolated_db, tmp_path):
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(
        app, ["report", "signoff", "NOM-IAM-03", "--framework", "nope", "--reviewer", "x"]
    )
    assert result.exit_code == 1
    assert "no mapping matched" in result.output
