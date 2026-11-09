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
