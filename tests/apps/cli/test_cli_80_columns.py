"""The first commands read cleanly in an 80-column terminal.

Found in the round-3 audit: `scan` padded the path column to half the terminal and
folded call sites mid-token (`client.chat.completions.cr` / `eate(...)`), printed the
scanned folder as an absolute path that wrapped mid-name, and said "1 files".
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentfox.apps.cli._style import display_path, plural
from agentfox.apps.cli.main import app

runner = CliRunner()

AGENT = """from openai import OpenAI

client = OpenAI()


def answer(q):
    return client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": q}])
"""


def test_plural_never_says_files_for_one():
    assert plural(1, "file") == "1 file"
    assert plural(2, "file") == "2 files"
    assert plural(3, "policy") == "3 policies"
    assert plural(2, "day") == "2 days"


def test_display_path_is_short(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert display_path(tmp_path) == "."
    (tmp_path / "sub").mkdir()
    assert display_path(tmp_path / "sub") == "./sub"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir("/")
    assert display_path(tmp_path / "sub") == "~/sub"


def test_scan_keeps_call_sites_whole_at_80_columns(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text(AGENT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "80")
    result = runner.invoke(app, ["scan", "."])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any("client.chat.completions.create(...)" in line for line in lines), result.output
    assert any("Scanned 1 file in ." in line for line in lines), result.output
    assert "1 files" not in result.output
    assert "call(s)" not in result.output
    assert all(len(line) <= 80 for line in lines), max(lines, key=len)


def test_scan_of_a_folder_elsewhere_names_it_without_wrapping(tmp_path, monkeypatch):
    deep = tmp_path / ("a-rather-long-directory-name-" * 3) / "agent"
    deep.mkdir(parents=True)
    (deep / "main.py").write_text(AGENT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "80")
    result = runner.invoke(app, ["scan", str(deep)])
    assert result.exit_code == 0, result.output
    shown = display_path(Path(deep))
    assert any(shown in line for line in result.output.splitlines()), result.output


def _finding() -> str:
    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding

    with session_scope() as session:
        finding = Finding(
            type="containment",
            severity="high",
            title="support-triage tried tickets.close without permission",
            subject_type="agent",
            subject_id="support-triage",
            evidence_json={"tool": "tickets.close", "rule": "capability.denied"},
        )
        session.add(finding)
        session.flush()
        return finding.id


def test_findings_show_opens_one_by_the_tail_the_list_prints():
    fid = _finding()
    listed = runner.invoke(app, ["findings"])
    assert listed.exit_code == 0, listed.output
    assert f"agentfox findings show {fid[-8:]}" in listed.output

    for typed in (fid, fid[-8:], f"…{fid[-8:]}"):
        shown = runner.invoke(app, ["findings", "show", typed])
        assert shown.exit_code == 0, shown.output
        assert fid in shown.output.splitlines()  # whole, on a line of its own
        assert "capability.denied" in shown.output

    as_json = runner.invoke(app, ["findings", "show", fid[-8:], "--json"])
    assert '"evidence"' in as_json.output


def test_findings_list_keeps_its_options():
    _finding()
    assert runner.invoke(app, ["findings", "--severity", "high"]).exit_code == 0
    assert runner.invoke(app, ["findings", "--json"]).exit_code == 0
    assert runner.invoke(app, ["findings", "--types"]).exit_code == 0


def test_findings_show_an_unknown_id_says_where_to_look():
    result = runner.invoke(app, ["findings", "show", "nothing"])
    assert result.exit_code == 2
    assert "agentfox findings" in result.output
