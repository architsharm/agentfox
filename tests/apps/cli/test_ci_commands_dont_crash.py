"""The CI page's commands, run as written (wow3 docs B5).

* ``test gate ... --junit reports/junit.xml`` crashed with a traceback in a fresh
  checkout: ``reports/`` didn't exist.
* ``policy simulate --file <missing>`` printed a traceback.
"""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()


def test_the_gate_writes_its_reports_into_a_folder_that_isnt_there_yet(seeded, tmp_path):
    seeded.commit()
    junit, sarif = tmp_path / "reports" / "junit.xml", tmp_path / "reports" / "agentfox.sarif"
    out = runner.invoke(
        app, ["test", "gate", "support-quality", "--junit", str(junit), "--sarif", str(sarif)]
    )
    assert out.exception is None or isinstance(out.exception, SystemExit), out.output
    assert junit.is_file() and sarif.is_file()


def test_simulating_a_missing_file_says_so_in_one_line(seeded, tmp_path):
    seeded.commit()
    out = runner.invoke(app, ["policy", "simulate", "--file", str(tmp_path / "nope.yaml")])
    assert out.exit_code == 2
    assert "No policy file at" in out.output and "Traceback" not in out.output
    bad = tmp_path / "bad.yaml"
    bad.write_text("this: is: not: a policy")
    out = runner.invoke(app, ["policy", "simulate", "--file", str(bad)])
    assert out.exit_code == 2 and "isn't a policy AgentFox can read" in out.output


def test_a_run_on_the_echo_model_says_it_proves_nothing_about_quality(seeded):
    """Runs on the default `echo` model showed 100% groundedness with no word that the
    model only repeats the prompt (wow3 prove)."""
    from agentfox.capabilities.evaluation.runner import ECHO_WARNING, NativeEvalRunner
    from agentfox.core.models import EvalSuite

    suite = seeded.query(EvalSuite).filter_by(key="support-quality").one()
    run = NativeEvalRunner().run(seeded, suite, {"provider": "echo"})
    assert run.summary_json["provider"] == "echo"
    assert run.summary_json["warning"] == ECHO_WARNING
    seeded.commit()
    out = runner.invoke(app, ["test", "run", "support-quality"], env={"COLUMNS": "200"})
    assert "offline echo model, which repeats the prompt" in " ".join(out.output.split())
