"""`agentfox report evidence --out`: the zip goes where you ask, and its path prints whole."""

from __future__ import annotations

import zipfile

from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()


def _seed() -> None:
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        seed(session)


def test_out_names_the_zip_file(tmp_path):
    _seed()
    target = tmp_path / "a very long directory name for the auditor" / "august-pack.zip"
    target.parent.mkdir()
    result = runner.invoke(app, ["report", "evidence", "--out", str(target)])
    assert result.exit_code == 0, result.output
    assert target.is_file()
    assert "verify_chain.py" in zipfile.ZipFile(target).namelist()
    # The path is on one line of its own, not wrapped by the console.
    assert str(target) in result.output.splitlines()


def test_out_can_be_a_directory(tmp_path):
    _seed()
    result = runner.invoke(app, ["report", "evidence", "--out", str(tmp_path / "packs")])
    assert result.exit_code == 0, result.output
    zips = list((tmp_path / "packs").glob("*.zip"))
    assert len(zips) == 1
    assert str(zips[0]) in result.output.splitlines()
