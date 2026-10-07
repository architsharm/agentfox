"""The pre-rename (Nometria) names: no longer read, but never silently ignored.

Stage B of finishing the rename. ``NOMETRIA_*`` variables, ``NOMETRIA_CONFIG``,
``nometria.toml`` / ``[nometria]`` and ``x-nometria-*`` headers are not read any more.
What stays is noticing them: a deployment that still sets an old name would otherwise
run on the default without a word, so the process logs one warning naming each
ignored setting and ``agentfox doctor`` lists every legacy variable still set.
"""

from __future__ import annotations

import json
import logging

import pytest
from typer.testing import CliRunner

from agentfox.core.config import (
    env,
    get_settings,
    ignored_legacy_settings,
    legacy_env_vars_set,
    reset_settings_cache,
)

LOGGER = "agentfox.core.config"


def fresh():
    reset_settings_cache()
    return get_settings()


def ignored_warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and "Ignored pre-rename" in r.message]


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A clean cwd with config-file loading on, and no config file yet."""
    cwd = tmp_path / "project"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("AGENTFOX_CONFIG", raising=False)
    monkeypatch.delenv("AGENTFOX_ENVIRONMENT", raising=False)
    reset_settings_cache()
    yield cwd
    reset_settings_cache()


# --- environment variables ----------------------------------------------------


def test_legacy_env_var_is_no_longer_read(monkeypatch):
    monkeypatch.delenv("AGENTFOX_ENFORCEMENT_BUDGET_MS", raising=False)
    default = fresh().enforcement_budget_ms
    monkeypatch.setenv("NOMETRIA_ENFORCEMENT_BUDGET_MS", str(default + 77))
    assert fresh().enforcement_budget_ms == default


def test_one_startup_warning_names_every_ignored_legacy_setting(monkeypatch, caplog):
    monkeypatch.setenv("NOMETRIA_ENFORCEMENT_BUDGET_MS", "123")
    monkeypatch.setenv("NOMETRIA_FAIL_MODE", "closed")
    # Replaced by its AGENTFOX_ twin: set, but nothing is lost by ignoring it.
    monkeypatch.setenv("NOMETRIA_ALLOW_EGRESS", "true")
    # What a Neon integration with the old prefix generates: never a setting.
    monkeypatch.setenv("NOMETRIA_DATABASE_POSTGRES_URL", "postgres://example/neon")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        fresh()
        fresh()  # a second Settings() in the same process says nothing new
    warnings = ignored_warnings(caplog)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "NOMETRIA_ENFORCEMENT_BUDGET_MS" in message
    assert "NOMETRIA_FAIL_MODE -> AGENTFOX_FAIL_MODE" in message
    assert "NOMETRIA_ALLOW_EGRESS" not in message
    assert "NOMETRIA_DATABASE_POSTGRES_URL" not in message


def test_no_warning_without_legacy_names(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        fresh()
    assert ignored_warnings(caplog) == []


def test_ignored_vs_set(monkeypatch):
    monkeypatch.setenv("NOMETRIA_FAIL_MODE", "closed")
    monkeypatch.setenv("NOMETRIA_ALLOW_EGRESS", "true")  # conftest sets AGENTFOX_
    monkeypatch.setenv("NOMETRIA_DATABASE_POSTGRES_URL", "postgres://example/neon")
    assert ignored_legacy_settings() == ["NOMETRIA_FAIL_MODE"]
    assert legacy_env_vars_set() == [
        "NOMETRIA_ALLOW_EGRESS",
        "NOMETRIA_DATABASE_POSTGRES_URL",
        "NOMETRIA_FAIL_MODE",
    ]


def test_direct_env_reads_only_the_agentfox_name(monkeypatch):
    monkeypatch.delenv("AGENTFOX_MCP_LOG_LEVEL", raising=False)
    monkeypatch.setenv("NOMETRIA_MCP_LOG_LEVEL", "INFO")
    assert env("MCP_LOG_LEVEL", "WARNING") == "WARNING"
    monkeypatch.setenv("AGENTFOX_MCP_LOG_LEVEL", "DEBUG")
    assert env("MCP_LOG_LEVEL") == "DEBUG"


def test_auto_agent_name_ignores_the_legacy_name(monkeypatch):
    from agentfox.frameworks.autoguard import default_agent_slug

    monkeypatch.delenv("AGENTFOX_AGENT", raising=False)
    monkeypatch.setenv("NOMETRIA_AGENT", "old-name")
    assert default_agent_slug() != "old-name"
    monkeypatch.setenv("AGENTFOX_AGENT", "support-bot")
    assert default_agent_slug() == "support-bot"


# --- config file --------------------------------------------------------------


def test_nometria_toml_is_not_read_and_is_named(workdir, caplog):
    (workdir / "nometria.toml").write_text('[nometria]\nenvironment = "staging"\n')
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        settings = fresh()
    assert settings.environment == "development"
    assert settings.config_file is None
    assert "nometria.toml" in ignored_warnings(caplog)[0].getMessage()


def test_legacy_table_in_agentfox_toml_is_not_read_and_is_named(workdir, caplog):
    (workdir / "agentfox.toml").write_text('[nometria]\nenvironment = "staging"\n')
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fresh().environment == "development"
    assert "[nometria]" in ignored_warnings(caplog)[0].getMessage()


def test_legacy_config_env_var_is_not_read(workdir, tmp_path, monkeypatch, caplog):
    elsewhere = tmp_path / "custom.toml"
    elsewhere.write_text('[agentfox]\nenvironment = "explicit"\n')
    monkeypatch.setenv("NOMETRIA_CONFIG", str(elsewhere))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fresh().environment == "development"
    assert "NOMETRIA_CONFIG" in ignored_warnings(caplog)[0].getMessage()


# --- agentfox doctor ----------------------------------------------------------


def _doctor() -> dict[str, dict]:
    from agentfox.apps.cli.main import app

    reset_settings_cache()
    result = CliRunner().invoke(app, ["doctor", "--json"])
    start = result.output.index("[")
    end = result.output.rindex("]") + 1
    return {row["check"]: row for row in json.loads(result.output[start:end])}


def test_doctor_lists_legacy_variables_still_set(monkeypatch):
    monkeypatch.setenv("NOMETRIA_FAIL_MODE", "closed")
    monkeypatch.setenv("NOMETRIA_DATABASE_POSTGRES_URL", "postgres://example/neon")
    row = _doctor()["legacy names"]
    assert row["state"] == "warn"
    assert "IGNORED, the default applies instead: NOMETRIA_FAIL_MODE" in row["detail"]
    assert "set but not read (safe to delete): NOMETRIA_DATABASE_POSTGRES_URL" in row["detail"]


def test_doctor_is_clean_without_legacy_names():
    assert _doctor()["legacy names"]["state"] == "ok"


# --- headers ------------------------------------------------------------------


def test_gateway_no_longer_accepts_the_legacy_user_header(client):
    from tests.conftest import as_user

    new = client.get("/api/me", headers=as_user("marcus@example.com"))
    assert new.json()["email"] == "marcus@example.com"
    legacy = client.get("/api/me", headers={"X-Nometria-User": "marcus@example.com"})
    # Treated as no identity header at all: the development default, not marcus.
    assert legacy.status_code != 200 or legacy.json()["email"] != "marcus@example.com"


def test_inline_route_ignores_legacy_headers_and_emits_only_new_ones(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Trace

    response = client.post(
        "/v1/chat/completions",
        json={"model": "echo-1", "messages": [{"role": "user", "content": "hello"}]},
        headers={"X-Nometria-Agent": "legacy-only-agent"},
    )
    assert response.status_code == 200, response.text
    emitted = {k.lower() for k in response.headers}
    assert "x-agentfox-trace" in emitted
    assert not [k for k in emitted if k.startswith("x-nometria-")]
    with session_scope() as session:
        trace = session.get(Trace, response.headers["X-AgentFox-Trace"])
        assert trace.agent_id is None  # the legacy agent header named nobody


def test_correlation_ignores_the_legacy_header():
    from agentfox.exporters.correlation import refs_from_headers

    assert refs_from_headers({"x-nometria-langfuse-trace": "old"}) == []
    refs = refs_from_headers({"x-agentfox-langfuse-trace": "new"})
    assert [r.external_trace_id for r in refs] == ["new"]
