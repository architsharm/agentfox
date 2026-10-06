"""#30, X1, #65 — promoting or listing a policy after a canary uses the live binding.

After a canary rollback the newest version is the rolled-back candidate. `policy
enforce` bound that version (re-shipping what the rollback removed) beside the
stable binding, leaving two open bindings; and the policy list read only the
newest version's binding, so a policy mid-canary or rolled back showed `unbound`.
"""

from __future__ import annotations

from sqlalchemy import select

from agentfox.core.models import Policy, PolicyBinding, PolicyVersion
from agentfox.platform.policy import (
    PolicyDocument,
    rollback_canary,
    save_policy,
    set_mode,
    start_canary,
)
from tests.conftest import as_user

V1 = "key: canary-mode\nmode: observe\nrules: []\n"
V2 = (
    "key: canary-mode\nmode: observe\n"
    "rules:\n  - id: x\n    when: {surface: [input]}\n    effect: block\n"
)


def _open_bindings(session) -> list[PolicyBinding]:
    policy = session.scalar(select(Policy).where(Policy.key == "canary-mode"))
    ids = [
        v.id
        for v in session.scalars(select(PolicyVersion).where(PolicyVersion.policy_id == policy.id))
    ]
    return list(
        session.scalars(
            select(PolicyBinding).where(
                PolicyBinding.policy_version_id.in_(ids), PolicyBinding.effective_to.is_(None)
            )
        )
    )


def test_enforce_after_rollback_promotes_the_stable_version_only(session):
    _p, v1 = save_policy(session, PolicyDocument.from_yaml(V1), bind_mode="observe")
    _p, _v2 = save_policy(session, PolicyDocument.from_yaml(V2), bind_mode="observe")
    canary = start_canary(session, "canary-mode", steps=[100])
    rollback_canary(session, canary.id)

    binding = set_mode(session, "canary-mode", "enforce")

    open_bindings = _open_bindings(session)
    assert len(open_bindings) == 1
    assert open_bindings[0].policy_version_id == v1.id
    assert binding is open_bindings[0] and binding.mode == "enforce"


def test_policy_list_shows_the_live_mode_during_and_after_a_canary(client):
    headers = as_user("marcus@example.com")
    client.post("/api/policies", json={"body": V1}, headers=headers)
    client.post("/api/policies", json={"body": V2}, headers=headers)
    started = client.post("/api/policies/canary-mode/canary/start", json={}, headers=headers)
    assert started.status_code == 201, started.text

    def listed() -> dict:
        rows = client.get("/api/policies", headers=headers).json()["policies"]
        return next(p for p in rows if p["key"] == "canary-mode")

    assert listed()["mode"] == "observe"
    client.post("/api/policies/canary-mode/canary/rollback", headers=headers)
    row = listed()
    assert row["mode"] == "observe"
    assert row["bound_version"] == 1
    assert row["latest_version"] == 2


def test_cli_policy_list_shows_the_live_mode_after_a_rollback(session):
    from typer.testing import CliRunner

    from agentfox.cli.main import app

    save_policy(session, PolicyDocument.from_yaml(V1), bind_mode="enforce")
    save_policy(session, PolicyDocument.from_yaml(V2), bind_mode="enforce")
    rollback_canary(session, start_canary(session, "canary-mode", steps=[100]).id)
    session.commit()

    out = CliRunner().invoke(app, ["policy", "list"]).output
    line = next(line for line in out.splitlines() if "canary-mode" in line)
    assert "enforce" in line and "unbound" not in line
