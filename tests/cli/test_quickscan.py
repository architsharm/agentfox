"""`agentfox quickscan` — the zero-account, zero-setup entry point. The whole point
is that it needs nothing: no database, no init, no GitHub, no network. These tests
deliberately do NOT use the `isolated_db` fixture other CLI tests rely on, because a
quickscan that secretly needed a database would be the exact bug this command exists
to not have.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentfox.cli.main import app

runner = CliRunner()


def flat(output: str) -> str:
    return " ".join(output.split())


def test_quickscan_runs_with_no_database_and_no_network(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "from openai import OpenAI\n"
        "client = OpenAI()\n"
        "def f():\n"
        "    client.chat.completions.create(model='gpt-4o', messages=[])\n"
    )
    result = runner.invoke(app, ["quickscan", str(tmp_path), "--skip-sessions"])
    assert result.exit_code == 0, result.output
    text = flat(result.output)
    assert "AgentFox Quickscan" in text
    assert "No account" in text


def test_quickscan_reports_live_detection_proof(tmp_path: Path):
    result = runner.invoke(app, ["quickscan", str(tmp_path), "--skip-sessions"])
    assert result.exit_code == 0
    text = flat(result.output)
    assert "Live proof" in text
    assert "adversarial probes caught" in text


def test_quickscan_json_output_is_structured(tmp_path: Path):
    result = runner.invoke(app, ["quickscan", str(tmp_path), "--skip-sessions", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "repo" in payload
    assert "sessions" in payload
    assert payload["sessions"] == []
    assert payload["live_demo"]["total"] > 0
    assert payload["live_demo"]["caught"] >= 1


def test_quickscan_skip_sessions_flag_omits_the_section(tmp_path: Path):
    result = runner.invoke(app, ["quickscan", str(tmp_path), "--skip-sessions"])
    assert "Actually running" not in flat(result.output)


def test_quickscan_includes_sessions_section_by_default(tmp_path: Path):
    result = runner.invoke(app, ["quickscan", str(tmp_path)])
    assert result.exit_code == 0
    assert "Actually running" in flat(result.output)


# ---------------------------------------------------------------------------
# --submit / --no-submit — the one optional exception to "nothing leaves this
# machine", and it must stay optional and explicit.
# ---------------------------------------------------------------------------


def test_no_submit_never_touches_the_network(tmp_path: Path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("httpx.post must not be called when --no-submit is passed")

    monkeypatch.setattr("agentfox.cli.submit.httpx.post", _boom)
    result = runner.invoke(app, ["quickscan", str(tmp_path), "--skip-sessions", "--no-submit"])
    assert result.exit_code == 0, result.output


def test_default_run_does_not_prompt_or_submit_when_not_a_tty(tmp_path: Path, monkeypatch):
    """CliRunner's stdio is never a real terminal, so with neither flag passed the
    interactive ask must not fire and nothing must be sent — an unattended `quickscan`
    (e.g. in a script) must not block on input or submit by surprise."""

    def _boom(*a, **k):
        raise AssertionError("nothing should be submitted with no flag on a non-tty run")

    monkeypatch.setattr("agentfox.cli.submit.httpx.post", _boom)
    result = runner.invoke(app, ["quickscan", str(tmp_path), "--skip-sessions"])
    assert result.exit_code == 0, result.output
    assert "Submit to the dashboard?" not in result.output


def test_submit_without_a_configured_control_plane_fails_gracefully(tmp_path: Path, monkeypatch):
    # Both names, because submit.py accepts AGENTFOX_ with NOMETRIA_ as the
    # legacy alias — unsetting only one leaves the other able to satisfy the
    # check this test exists to exercise.
    monkeypatch.delenv("AGENTFOX_API_URL", raising=False)
    monkeypatch.delenv("NOMETRIA_API_URL", raising=False)
    result = runner.invoke(app, ["quickscan", str(tmp_path), "--skip-sessions", "--submit"])
    assert result.exit_code == 0, result.output
    assert "Could not submit" in flat(result.output)
    assert "AGENTFOX_API_URL" in flat(result.output)


def test_submit_posts_only_the_redacted_payload(tmp_path: Path, monkeypatch):
    (tmp_path / "app.py").write_text(
        "import subprocess\nsubprocess.run('echo super-secret-internal-flag')\n"
    )
    monkeypatch.setenv("NOMETRIA_API_URL", "https://plane.example.internal")
    monkeypatch.setenv("NOMETRIA_API_TOKEN", "nom_usr_test")

    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "scan_run_id": "scn_test",
                "summary": {"agents_proposed": [], "policies_proposed": []},
            }

    def _fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr("agentfox.cli.submit.httpx.post", _fake_post)

    result = runner.invoke(app, ["quickscan", str(tmp_path), "--skip-sessions", "--submit"])
    assert result.exit_code == 0, result.output
    assert "Submitted." in flat(result.output)
    assert captured["url"] == "https://plane.example.internal/api/discovery/submit"
    assert captured["headers"]["Authorization"] == "Bearer nom_usr_test"
    assert "super-secret-internal-flag" not in repr(captured["json"])
    assert "detail" not in repr(captured["json"])
