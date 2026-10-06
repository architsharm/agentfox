"""A stored policy version that no longer validates must not take the product down.

Production held a bound `tool-containment` version saved before
`control_plane.tamper` became a protected rule. Every path that turned that
binding into a document re-validated it, the validator refused it, and
`/api/coverage/threats` answered 500. On this branch the same read is the
runtime's, so every guard call for that tenant would have failed too.

Two cases, kept apart on purpose:

* **Only a protected rule is missing.** The rule is non-overridable and the pack
  may not run without it, so the stored version gets the shipped rule back and
  loads — the rule it was always meant to carry.
* **Anything else is wrong.** Nothing is guessed. The runtime treats it like a
  degraded pipeline under the deployment's fail mode; read-only views skip the
  layer and say so.

The rows are written directly, because the save path refuses both shapes and the
point is data that got past it before the rule existed.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from agentfox.core.models import Policy, PolicyBinding, PolicyVersion, utcnow
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
TAMPER = "control_plane.tamper"


def _bound_version(session, key: str) -> PolicyVersion:
    from agentfox.platform.policy.store import current_binding

    policy = session.scalar(select(Policy).where(Policy.key == key))
    _binding, version = current_binding(session, policy.id)
    return version


def _bind_raw(session, key: str, compiled: dict) -> PolicyVersion:
    """Insert version n+1 of ``key`` with ``compiled`` as-is and bind it, bypassing
    every validator, the way an old row written before the rule existed looks."""
    import yaml

    old = _bound_version(session, key)
    old_binding = session.scalar(
        select(PolicyBinding).where(
            PolicyBinding.policy_version_id == old.id, PolicyBinding.effective_to.is_(None)
        )
    )
    latest = session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == old.policy_id)
        .order_by(PolicyVersion.version.desc())
    ).first()
    version = PolicyVersion(
        policy_id=old.policy_id,
        version=latest.version + 1,
        body=yaml.safe_dump(compiled, sort_keys=False),
        compiled_json=compiled,
        author="legacy",
        notes="written before the protected rule existed",
    )
    session.add(version)
    session.flush()
    old_binding.effective_to = utcnow()
    session.add(
        PolicyBinding(
            policy_version_id=version.id,
            scope_json=old_binding.scope_json,
            mode=old_binding.mode,
            level=old_binding.level,
            scope_id=old_binding.scope_id,
            compose=old_binding.compose,
            effective_from=old_binding.effective_to,
        )
    )
    session.flush()
    return version


def _without_tamper(session) -> dict:
    compiled = dict(_bound_version(session, "tool-containment").compiled_json)
    compiled["rules"] = [r for r in compiled["rules"] if r.get("id") != TAMPER]
    assert len(compiled["rules"]) > 0
    return compiled


def _broken(session, key: str = "tool-containment", fail_mode: str = "open") -> dict:
    """Not a protected-rule gap: a rule with an effect that does not exist."""
    compiled = dict(_bound_version(session, key).compiled_json)
    compiled["fail_mode"] = fail_mode
    compiled["rules"] = [*compiled["rules"], {"id": "legacy.rule", "effect": "explode"}]
    return compiled


@pytest.fixture
def shell_agent(seeded):
    from agentfox.core.models import Agent
    from agentfox.identity import ensure_identity, grant_capability

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    identity = ensure_identity(seeded, agent)
    grant_capability(seeded, identity, "shell.run", max_taint="tool_result")
    return agent


def _tamper_call(enforcer):
    return enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="shell.run",
        arguments={"command": "agentfox policy observe baseline"},
    )


# ---------------------------------------------------------------------------
# A stored version that only lacks a protected rule
# ---------------------------------------------------------------------------


def test_coverage_answers_with_a_legacy_version_bound(client):
    from agentfox.core.db import session_scope

    with session_scope() as s:
        _bind_raw(s, "tool-containment", _without_tamper(s))

    response = client.get("/api/coverage/threats", headers=ADMIN)
    assert response.status_code == 200, response.text
    assert response.json()["unloadable_policies"] == []


def test_the_runtime_evaluates_the_restored_rule(seeded, shell_agent, caplog):
    from agentfox.platform.policy import policies_in_force
    from agentfox.runtime.enforcement import Enforcer

    version = _bind_raw(seeded, "tool-containment", _without_tamper(seeded))

    with caplog.at_level(logging.WARNING, logger="agentfox.platform.policy.store"):
        in_force = policies_in_force(seeded, "support-triage")
    pack = next(doc for doc, _v, _b in in_force if doc.key == "tool-containment")
    assert TAMPER in {rule.id for rule in pack.rules}
    warning = next(r for r in caplog.records if TAMPER in r.getMessage())
    assert "tool-containment" in warning.getMessage()
    assert f"v{version.version}" in warning.getMessage()

    result = _tamper_call(Enforcer(seeded))
    assert result.blocked
    assert TAMPER in {r["rule_id"] for r in result.rules_fired}


def test_only_protected_rules_are_restored(seeded):
    """The loader restores the protected rule and nothing else the pack ships."""
    from agentfox.platform.policy.store import load_from_dir, load_version_document

    compiled = _without_tamper(seeded)
    compiled["rules"] = compiled["rules"][:1]
    version = _bind_raw(seeded, "tool-containment", compiled)

    doc = load_version_document(version)
    shipped = next(d for d in load_from_dir() if d.key == "tool-containment")
    assert len(shipped.rules) > 2
    assert [r.id for r in doc.rules] == [compiled["rules"][0]["id"], TAMPER]


def test_saving_a_document_without_the_protected_rule_is_still_refused(client):
    """A regression guard: the leniency is for stored rows only, never for a save."""
    import yaml

    from agentfox.platform.policy import PolicyDocument

    body = yaml.safe_dump({"key": "tool-containment", "rules": [{"id": "something.else"}]})
    with pytest.raises(Exception, match=TAMPER):
        PolicyDocument.from_yaml(body)
    response = client.post("/api/policies", json={"body": body}, headers=ADMIN)
    assert response.status_code == 400
    assert TAMPER in response.json()["detail"]


# ---------------------------------------------------------------------------
# A stored version that is broken some other way
# ---------------------------------------------------------------------------


def test_policies_in_force_names_the_broken_version(seeded):
    from agentfox.platform.policy import UnloadablePolicyVersion, policies_in_force

    version = _bind_raw(seeded, "tool-containment", _broken(seeded))
    with pytest.raises(UnloadablePolicyVersion) as excinfo:
        policies_in_force(seeded, "support-triage")
    assert excinfo.value.key == "tool-containment"
    assert excinfo.value.version == version.version
    assert f"tool-containment v{version.version}" in str(excinfo.value)


def test_a_fail_open_deployment_allows_and_records_why(seeded, shell_agent):
    from agentfox.runtime.enforcement import Enforcer

    _bind_raw(seeded, "tool-containment", _broken(seeded, fail_mode="open"))
    enforcer = Enforcer(seeded)
    assert enforcer.settings.fail_mode == "open"

    result = enforcer.guard_tool_call(
        agent_slug="support-triage", tool_key="shell.run", arguments={"command": "ls"}
    )
    assert not result.blocked
    fired = next(r for r in result.rules_fired if r["rule_id"] == "policy.unloadable")
    assert fired["effect"] == "allow"
    assert "tool-containment" in fired["reason"]


def test_a_fail_closed_deployment_blocks(seeded, shell_agent, monkeypatch):
    from agentfox.core.config import reset_settings_cache
    from agentfox.runtime.enforcement import Enforcer

    _bind_raw(seeded, "tool-containment", _broken(seeded, fail_mode="open"))
    monkeypatch.setenv("AGENTFOX_FAIL_MODE", "closed")
    reset_settings_cache()
    enforcer = Enforcer(seeded)
    assert enforcer.settings.fail_mode == "closed"

    result = enforcer.guard_tool_call(
        agent_slug="support-triage", tool_key="shell.run", arguments={"command": "ls"}
    )
    assert result.blocked
    fired = next(r for r in result.rules_fired if r["rule_id"] == "policy.unloadable")
    assert fired["effect"] == "block"


def test_a_pack_that_declared_fail_closed_blocks_on_its_own(seeded, shell_agent):
    """The stricter of the two sources wins, as for a degraded pipeline (#42)."""
    from agentfox.runtime.enforcement import Enforcer

    _bind_raw(seeded, "tool-containment", _broken(seeded, fail_mode="closed"))
    result = Enforcer(seeded).guard_tool_call(
        agent_slug="support-triage", tool_key="shell.run", arguments={"command": "ls"}
    )
    assert result.blocked
    assert "policy.unloadable" in {r["rule_id"] for r in result.rules_fired}


def test_read_only_views_skip_and_surface_the_broken_layer(client):
    from agentfox.core.db import session_scope

    with session_scope() as s:
        version = _bind_raw(s, "tool-containment", _broken(s)).version

    coverage = client.get("/api/coverage/threats", headers=ADMIN)
    assert coverage.status_code == 200, coverage.text
    [entry] = coverage.json()["unloadable_policies"]
    assert entry["key"] == "tool-containment" and entry["version"] == version

    lint = client.get("/api/policies/lint", headers=ADMIN)
    assert lint.status_code == 200, lint.text
    finding = next(f for f in lint.json()["findings"] if f["code"] == "unloadable-version")
    assert "tool-containment" in finding["message"]

    effective = client.get("/api/policies/effective?agent=support-triage", headers=ADMIN)
    assert effective.status_code == 200, effective.text
    assert effective.json()["unloadable_policies"][0]["key"] == "tool-containment"

    listed = client.get("/api/policies?agent=support-triage", headers=ADMIN)
    assert listed.status_code == 200, listed.text
    assert listed.json()["unloadable_policies"][0]["key"] == "tool-containment"
