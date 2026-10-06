"""agentfox.toml — written by `agentfox init`, and now actually read.

Precedence, highest first: init kwargs > NOMETRIA_* env > [agentfox] table > defaults.
"""

from __future__ import annotations

import logging

import pytest

from agentfox.core.config import (
    ConfigFileError,
    Settings,
    get_settings,
    loaded_config_file,
    reset_settings_cache,
)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A clean cwd with no config file and no explicit NOMETRIA_CONFIG."""
    cwd = tmp_path / "project"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    # Both spellings, because Settings reads both prefixes and the current one wins.
    for var in (
        "AGENTFOX_CONFIG",
        "NOMETRIA_CONFIG",
        "AGENTFOX_ENVIRONMENT",
        "AGENTFOX_DEFAULT_POLICY_MODE",
        "AGENTFOX_ENABLED_DETECTORS",
        "NOMETRIA_ENVIRONMENT",
        "NOMETRIA_DEFAULT_POLICY_MODE",
        "NOMETRIA_ENABLED_DETECTORS",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_settings_cache()
    yield cwd
    reset_settings_cache()


def fresh() -> Settings:
    reset_settings_cache()
    return get_settings()


def test_no_file_means_defaults(workdir):
    settings = fresh()
    assert settings.environment == "development"
    assert settings.default_policy_mode == "observe"
    assert settings.config_file is None
    assert loaded_config_file() is None


def test_toml_value_is_applied(workdir):
    path = workdir / "agentfox.toml"
    path.write_text('[agentfox]\nenvironment = "staging"\ndefault_policy_mode = "enforce"\n')
    settings = fresh()
    assert settings.environment == "staging"
    assert settings.default_policy_mode == "enforce"
    assert settings.config_file == path.resolve()
    assert loaded_config_file() == path.resolve()


def test_env_overrides_toml(workdir, monkeypatch):
    (workdir / "agentfox.toml").write_text(
        '[agentfox]\nenvironment = "staging"\nenforcement_budget_ms = 120\n'
    )
    monkeypatch.setenv("NOMETRIA_ENVIRONMENT", "production")
    settings = fresh()
    assert settings.environment == "production"  # env wins
    assert settings.enforcement_budget_ms == 120  # file still fills the rest


def test_init_kwargs_override_env_and_toml(workdir, monkeypatch):
    (workdir / "agentfox.toml").write_text('[agentfox]\nenvironment = "staging"\n')
    monkeypatch.setenv("NOMETRIA_ENVIRONMENT", "production")
    assert Settings(environment="explicit").environment == "explicit"


def test_explicit_path_via_nometria_config(workdir, tmp_path, monkeypatch):
    # A cwd file exists too; the explicit path must win over it.
    (workdir / "agentfox.toml").write_text('[agentfox]\nenvironment = "cwd"\n')
    elsewhere = tmp_path / "etc" / "custom.toml"
    elsewhere.parent.mkdir()
    elsewhere.write_text('[agentfox]\nenvironment = "explicit"\n')
    monkeypatch.setenv("NOMETRIA_CONFIG", str(elsewhere))
    settings = fresh()
    assert settings.environment == "explicit"
    assert settings.config_file == elsewhere.resolve()


def test_missing_explicit_path_is_an_error(workdir, tmp_path, monkeypatch):
    missing = tmp_path / "nope.toml"
    monkeypatch.setenv("NOMETRIA_CONFIG", str(missing))
    with pytest.raises(ConfigFileError, match="nope.toml"):
        fresh()


def test_unknown_key_is_ignored_with_a_warning(workdir, caplog):
    (workdir / "agentfox.toml").write_text(
        '[agentfox]\nenvironment = "staging"\nenviroment_typo = "x"\n'
    )
    with caplog.at_level(logging.WARNING, logger="agentfox.core.config"):
        settings = fresh()
    assert settings.environment == "staging"
    assert not hasattr(settings, "enviroment_typo")
    assert "enviroment_typo" in caplog.text


def test_list_field_from_toml_array_and_types_coerced(workdir, monkeypatch):
    monkeypatch.delenv("NOMETRIA_ALLOW_EGRESS", raising=False)  # conftest sets it; env wins
    (workdir / "agentfox.toml").write_text(
        "[agentfox]\n"
        'enabled_detectors = ["pii.native", "secrets.native"]\n'
        "allow_egress = true\n"
        'enforcement_budget_ms = "250"\n'  # string coerced to int, as from env
    )
    settings = fresh()
    assert settings.enabled_detectors == ["pii.native", "secrets.native"]
    assert settings.allow_egress is True
    assert settings.enforcement_budget_ms == 250


def test_invalid_toml_value_fails_validation(workdir):
    (workdir / "agentfox.toml").write_text('[agentfox]\nenforcement_budget_ms = "fast"\n')
    with pytest.raises(Exception, match="enforcement_budget_ms"):
        fresh()


def test_other_tables_ignored_and_missing_table_is_harmless(workdir):
    path = workdir / "agentfox.toml"
    path.write_text('[tool.other]\nenvironment = "wrong"\n')
    assert fresh().environment == "development"
    path.write_text("# hand-edited\n")
    assert fresh().environment == "development"


def test_the_file_nometria_init_writes_is_read(workdir, isolated_db):
    from typer.testing import CliRunner

    from agentfox.apps.cli.main import app

    result = CliRunner().invoke(app, ["init", "--path", str(workdir)])
    assert result.exit_code == 0, result.output
    settings = fresh()
    assert settings.config_file == (workdir / "agentfox.toml").resolve()
    assert settings.default_policy_mode == "observe"
    assert settings.allow_egress is False


def test_config_none_turns_file_loading_off(workdir, monkeypatch):
    """CI, containers and the test suite itself need a way to say 'env and defaults only'."""
    (workdir / "agentfox.toml").write_text('[agentfox]\nenvironment = "staging"\n')
    monkeypatch.setenv("NOMETRIA_CONFIG", "none")
    settings = fresh()
    assert settings.environment == "development"
    assert loaded_config_file() is None


def test_direct_env_reads_prefer_agentfox_and_keep_the_legacy_name(monkeypatch):
    """Switches read outside Settings follow Settings' own precedence."""
    from agentfox.core.config import env

    monkeypatch.delenv("AGENTFOX_MCP_LOG_LEVEL", raising=False)
    monkeypatch.delenv("NOMETRIA_MCP_LOG_LEVEL", raising=False)
    assert env("MCP_LOG_LEVEL", "WARNING") == "WARNING"
    monkeypatch.setenv("NOMETRIA_MCP_LOG_LEVEL", "INFO")
    assert env("MCP_LOG_LEVEL") == "INFO"
    monkeypatch.setenv("AGENTFOX_MCP_LOG_LEVEL", "DEBUG")
    assert env("MCP_LOG_LEVEL") == "DEBUG"


def test_auto_agent_name_reads_agentfox_agent_first(monkeypatch):
    from agentfox.frameworks.autoguard import default_agent_slug

    monkeypatch.setenv("NOMETRIA_AGENT", "old-name")
    assert default_agent_slug() == "old-name"
    monkeypatch.setenv("AGENTFOX_AGENT", "support-bot")
    assert default_agent_slug() == "support-bot"
