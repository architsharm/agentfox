"""The pre-rename (Nometria) names: still read, never written, and said out loud.

Stage A of finishing the rename. Production still sets ``NOMETRIA_*`` variables, so
they keep working as a fallback below ``AGENTFOX_*``; but the process says so once at
startup, naming each one in use, and ``agentfox doctor`` lists every one still set,
so the deployment can be renamed before the fallback is removed. Same for a
``nometria.toml`` / ``[nometria]`` config file, and for ``x-nometria-*`` request
headers, which are accepted with ``x-agentfox-*`` winning and never emitted.
"""

from __future__ import annotations

import json
import logging

import pytest
from typer.testing import CliRunner

from agentfox.core.config import (
    env,
    get_settings,
    legacy_env_vars_set,
    legacy_settings_in_use,
    reset_settings_cache,
)
from agentfox.core.headers import get_header, normalize_asgi_headers
from tests.conftest import as_user

LOGGER = "agentfox.core.config"


def fresh():
    reset_settings_cache()
    return get_settings()


def legacy_warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and "Deprecated pre-rename" in r.message]


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


def test_legacy_env_var_still_reaches_settings(monkeypatch):
    monkeypatch.delenv("AGENTFOX_ENFORCEMENT_BUDGET_MS", raising=False)
    monkeypatch.setenv("NOMETRIA_ENFORCEMENT_BUDGET_MS", "123")
    assert fresh().enforcement_budget_ms == 123


def test_agentfox_wins_over_the_legacy_name(monkeypatch):
    monkeypatch.setenv("NOMETRIA_ENFORCEMENT_BUDGET_MS", "123")
    monkeypatch.setenv("AGENTFOX_ENFORCEMENT_BUDGET_MS", "456")
    assert fresh().enforcement_budget_ms == 456


def test_one_startup_warning_names_every_legacy_variable_in_use(monkeypatch, caplog):
    monkeypatch.setenv("NOMETRIA_ENFORCEMENT_BUDGET_MS", "123")
    monkeypatch.setenv("NOMETRIA_FAIL_MODE", "closed")
    # Shadowed by its AGENTFOX_ twin: set, but not the value in use.
    monkeypatch.setenv("NOMETRIA_ALLOW_EGRESS", "true")
    # What a Neon integration with the old prefix generates: read by nothing.
    monkeypatch.setenv("NOMETRIA_DATABASE_POSTGRES_URL", "postgres://example/neon")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        fresh()
        fresh()  # a second Settings() in the same process says nothing new
        assert env("ENFORCEMENT_BUDGET_MS") == "123"
    warnings = legacy_warnings(caplog)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "NOMETRIA_ENFORCEMENT_BUDGET_MS" in message
    assert "NOMETRIA_FAIL_MODE" in message
    assert "AGENTFOX_FAIL_MODE" in message  # says what to rename it to
    assert "NOMETRIA_ALLOW_EGRESS" not in message
    assert "NOMETRIA_DATABASE_POSTGRES_URL" not in message


def test_no_warning_without_legacy_names(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        fresh()
    assert legacy_warnings(caplog) == []


def test_set_vs_in_use(monkeypatch):
    monkeypatch.setenv("NOMETRIA_FAIL_MODE", "closed")
    monkeypatch.setenv("NOMETRIA_ALLOW_EGRESS", "true")  # shadowed (conftest sets AGENTFOX_)
    monkeypatch.setenv("NOMETRIA_DATABASE_POSTGRES_URL", "postgres://example/neon")
    assert legacy_settings_in_use() == ["NOMETRIA_FAIL_MODE"]
    assert legacy_env_vars_set() == [
        "NOMETRIA_ALLOW_EGRESS",
        "NOMETRIA_DATABASE_POSTGRES_URL",
        "NOMETRIA_FAIL_MODE",
    ]


def test_direct_env_reads_prefer_agentfox_and_keep_the_legacy_name(monkeypatch, caplog):
    """Switches read outside Settings follow Settings' own precedence and warning."""
    monkeypatch.delenv("AGENTFOX_MCP_LOG_LEVEL", raising=False)
    assert env("MCP_LOG_LEVEL", "WARNING") == "WARNING"
    monkeypatch.setenv("NOMETRIA_MCP_LOG_LEVEL", "INFO")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert env("MCP_LOG_LEVEL") == "INFO"
    assert "NOMETRIA_MCP_LOG_LEVEL" in legacy_warnings(caplog)[0].getMessage()
    monkeypatch.setenv("AGENTFOX_MCP_LOG_LEVEL", "DEBUG")
    assert env("MCP_LOG_LEVEL") == "DEBUG"


def test_auto_agent_name_reads_agentfox_agent_first(monkeypatch):
    from agentfox.frameworks.autoguard import default_agent_slug

    monkeypatch.delenv("AGENTFOX_AGENT", raising=False)
    monkeypatch.setenv("NOMETRIA_AGENT", "old-name")
    assert default_agent_slug() == "old-name"
    monkeypatch.setenv("AGENTFOX_AGENT", "support-bot")
    assert default_agent_slug() == "support-bot"


def test_submit_reads_the_legacy_api_url(monkeypatch):
    from agentfox.apps.cli import submit

    monkeypatch.delenv("AGENTFOX_API_URL", raising=False)
    monkeypatch.delenv("AGENTFOX_API_TOKEN", raising=False)
    monkeypatch.delenv("AGENTFOX_USER", raising=False)
    monkeypatch.setenv("NOMETRIA_API_URL", "https://plane.example.internal")
    # No credential: it gets as far as asking for one, so the URL was found.
    with pytest.raises(submit.SubmissionUnavailable, match="no credentials"):
        submit.submit_scan_report(object(), source="check")  # type: ignore[arg-type]


# --- config file --------------------------------------------------------------


def test_nometria_toml_is_still_read_with_the_warning(workdir, caplog):
    (workdir / "nometria.toml").write_text('[nometria]\nenvironment = "staging"\n')
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        settings = fresh()
    assert settings.environment == "staging"
    assert settings.config_file == (workdir / "nometria.toml").resolve()
    message = legacy_warnings(caplog)[0].getMessage()
    assert "nometria.toml" in message
    assert "[nometria]" in message


def test_agentfox_toml_wins_over_nometria_toml(workdir, caplog):
    (workdir / "agentfox.toml").write_text('[agentfox]\nenvironment = "staging"\n')
    (workdir / "nometria.toml").write_text('[nometria]\nenvironment = "old"\n')
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fresh().environment == "staging"
    assert legacy_warnings(caplog) == []


def test_legacy_table_in_agentfox_toml_is_read_with_the_warning(workdir, caplog):
    (workdir / "agentfox.toml").write_text('[nometria]\nenvironment = "staging"\n')
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fresh().environment == "staging"
    assert "[nometria]" in legacy_warnings(caplog)[0].getMessage()


def test_legacy_config_env_var_points_at_a_file(workdir, tmp_path, monkeypatch, caplog):
    elsewhere = tmp_path / "custom.toml"
    elsewhere.write_text('[agentfox]\nenvironment = "explicit"\n')
    monkeypatch.setenv("NOMETRIA_CONFIG", str(elsewhere))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fresh().environment == "explicit"
    assert "NOMETRIA_CONFIG" in legacy_warnings(caplog)[0].getMessage()


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
    assert "in use: NOMETRIA_FAIL_MODE" in row["detail"]
    assert "NOMETRIA_DATABASE_POSTGRES_URL" in row["detail"]
    assert "AGENTFOX_" in row["detail"]


def test_doctor_is_clean_without_legacy_names():
    row = _doctor()["legacy names"]
    assert row["state"] == "ok"


# --- headers ------------------------------------------------------------------


def test_normalize_renames_legacy_headers_and_the_new_name_wins():
    raw = [
        (b"x-nometria-agent", b"old-agent"),
        (b"X-Nometria-Session", b"s-1"),
        (b"x-agentfox-agent", b"new-agent"),
        (b"content-type", b"application/json"),
    ]
    assert normalize_asgi_headers(raw) == [
        (b"x-agentfox-session", b"s-1"),
        (b"x-agentfox-agent", b"new-agent"),
        (b"content-type", b"application/json"),
    ]
    untouched = [(b"x-agentfox-agent", b"a")]
    assert normalize_asgi_headers(untouched) is untouched


def test_get_header_prefers_the_new_name():
    assert get_header({"x-nometria-agent": "old"}, "agent") == "old"
    assert get_header({"x-nometria-agent": "old", "x-agentfox-agent": "new"}, "agent") == "new"
    assert get_header({}, "agent") is None


def test_gateway_accepts_the_legacy_user_header_and_prefers_the_new_one(client):
    legacy = client.get("/api/me", headers={"X-Nometria-User": "marcus@example.com"})
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["email"] == "marcus@example.com"
    both = client.get(
        "/api/me",
        headers={**as_user("admin@example.com"), "X-Nometria-User": "marcus@example.com"},
    )
    assert both.json()["email"] == "admin@example.com"


def _completion(client, headers):
    response = client.post(
        "/v1/chat/completions",
        json={"model": "echo-1", "messages": [{"role": "user", "content": "hello"}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response


def _agent_of(trace_id: str) -> str:
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Trace

    with session_scope() as session:
        trace = session.get(Trace, trace_id)
        return session.get(Agent, trace.agent_id).slug


def test_inline_route_accepts_legacy_headers_and_emits_only_new_ones(client):
    response = _completion(
        client,
        {"X-Nometria-Agent": "support-triage", "x-nometria-langfuse-trace": "lf-legacy"},
    )
    emitted = {k.lower() for k in response.headers}
    assert "x-agentfox-trace" in emitted
    assert "x-agentfox-verdict" in emitted
    assert not [k for k in emitted if k.startswith("x-nometria-")]
    trace_id = response.headers["X-AgentFox-Trace"]
    assert _agent_of(trace_id) == "support-triage"
    body = client.get(f"/api/traces/{trace_id}", headers=as_user("admin@example.com")).json()
    assert body["links"][0]["external_trace_id"] == "lf-legacy"


def test_inline_route_prefers_the_new_header_when_both_are_sent(client):
    response = _completion(
        client,
        {"X-AgentFox-Agent": "support-triage", "X-Nometria-Agent": "someone-else"},
    )
    assert _agent_of(response.headers["X-AgentFox-Trace"]) == "support-triage"


def test_correlation_prefers_the_new_header():
    from agentfox.exporters.correlation import refs_from_headers

    refs = refs_from_headers(
        {"x-nometria-langfuse-trace": "old", "x-agentfox-langfuse-trace": "new"}
    )
    assert [r.external_trace_id for r in refs] == ["new"]
