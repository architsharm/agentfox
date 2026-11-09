"""`agentfox admin detectors pull injection.classifier` says what it downloads and why.

It fetched two models with no word about the second (the backstop)."""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()


def test_pull_names_each_model_and_its_role(monkeypatch):
    from agentfox.capabilities.detection import models

    monkeypatch.setattr(models, "pull", lambda detector: models.models_for(detector))
    result = runner.invoke(
        app, ["admin", "detectors", "pull", "injection.classifier"], env={"COLUMNS": "200"}
    )

    assert result.exit_code == 0, result.output
    assert "Downloading 2 models for injection.classifier" in result.output
    assert "the model it checks with" in result.output
    assert "a second opinion" in result.output
