"""The onboarding flow held to the rest of the product's rules: the setup key is a
credential like an operator token, it can only propose agents, guardrails go through
the simulate-before-enforce gate, payloads are validated, and test runs survive races
and dead runners."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from agentfox.capabilities.onboarding import runner as runner_mod
from agentfox.capabilities.onboarding import service
from agentfox.core.db import session_scope
from agentfox.core.models import (
    Agent,
    ApiToken,
    AuditEntry,
    Capability,
    Identity,
    OnboardingRun,
    OnboardingSession,
    User,
    utcnow,
)
from agentfox.core.tenancy import system_scope
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
DEV = as_user("priya@example.com")
AUDITOR = as_user("aisha@example.com")


def _structure(name: str = "Shop Agent", tools: tuple[str, ...] = ("get_order",)) -> dict:
    return {
        "sources": [],
        "agents": [{"id": "ag-1", "name": name, "model": "gpt-4o-mini", "sourceIds": []}],
        "tools": [
            {"id": f"t{i}", "name": t, "agentId": "ag-1", "risk": "high", "systemId": "s"}
            for i, t in enumerate(tools)
        ],
        "systems": [{"id": "s", "name": "Orders", "kind": "database"}],
    }


def _key(client, headers=ADMIN) -> str:
    return client.get("/api/onboarding/key", headers=headers).json()["value"]


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _connect(client, key, structure=None, project="shop"):
    return client.post(
        "/api/onboarding/runner/connect",
        json={"structure": structure or _structure(), "project": project},
        headers=_bearer(key),
    )


# --- 1a. the setup key is a credential ---------------------------------------------


def test_the_setup_key_is_stored_hashed_and_shown_once(client):
    first = client.get("/api/onboarding/key", headers=ADMIN).json()
    raw = first["value"]
    assert raw.startswith("afi_") and first["createdNow"] is True
    assert first["prefix"] == raw[: len(first["prefix"])] and first["expiresAt"]

    again = client.get("/api/onboarding/key", headers=ADMIN).json()
    assert again["value"] is None and again["createdNow"] is False
    assert again["prefix"] == first["prefix"] and again["hasKey"] is True

    with session_scope() as s, system_scope("test"):
        assert s.scalar(select(OnboardingSession).where(OnboardingSession.init_key == raw)) is None
        token = s.scalar(select(ApiToken).where(ApiToken.key_prefix == first["prefix"]))
        assert token is not None and raw not in token.key_hash
    assert _connect(client, raw).status_code == 200


def test_rotating_the_setup_key_ends_the_old_one(client):
    old = _key(client)
    assert _connect(client, old).status_code == 200
    rotated = client.post("/api/onboarding/key/rotate", headers=ADMIN)
    assert rotated.status_code == 200
    new = rotated.json()["value"]
    assert new and new != old
    assert _connect(client, old).status_code == 401
    assert _connect(client, new).status_code == 200
    # Listed with the user's tokens, so it can be revoked there too.
    names = [t["name"] for t in client.get("/api/tokens", headers=ADMIN).json()["tokens"]]
    assert "agentfox init setup key" in names


def test_an_expired_setup_key_is_refused(client):
    key = _key(client)
    with session_scope() as s, system_scope("test"):
        for t in s.scalars(select(ApiToken).where(ApiToken.name == "agentfox init setup key")):
            t.expires_at = utcnow() - dt.timedelta(minutes=1)
    assert _connect(client, key).status_code == 401
    # Asking again makes a fresh one.
    fresh = client.get("/api/onboarding/key", headers=ADMIN).json()
    assert fresh["createdNow"] is True and _connect(client, fresh["value"]).status_code == 200


@pytest.mark.parametrize("change", [{"active": False}, {"role": "auditor"}])
def test_the_setup_key_stops_with_its_owner(client, change):
    key = _key(client, DEV)
    assert _connect(client, key).status_code == 200
    with session_scope() as s, system_scope("test"):
        user = s.scalar(select(User).where(User.email == "priya@example.com"))
        for k, v in change.items():
            setattr(user, k, v)
    assert _connect(client, key).status_code == 403
    assert client.post("/api/onboarding/runner/poll", headers=_bearer(key)).status_code == 403


def test_a_read_only_role_cannot_make_a_setup_key(client):
    assert client.get("/api/onboarding/key", headers=AUDITOR).status_code == 403
    assert client.post("/api/onboarding/key/rotate", headers=AUDITOR).status_code == 403


def test_a_plaintext_key_from_before_hashing_is_moved_to_a_token_on_first_use(client):
    legacy = "afi_" + "L" * 32
    with session_scope() as s, system_scope("test"):
        user = s.scalar(select(User).where(User.email == "admin@example.com"))
        s.add(
            OnboardingSession(
                user_id=user.id, org_id=user.org_id, init_key=legacy, state={}, runs={}
            )
        )
    assert _connect(client, legacy).status_code == 200
    with session_scope() as s, system_scope("test"):
        row = s.scalar(select(OnboardingSession))
        assert row.init_key.startswith("tok_")
    assert _connect(client, legacy).status_code == 200


# --- 1c. the key proposes; it never changes what is live -----------------------------


def test_connect_cannot_change_or_grant_an_existing_agent(client):
    before = client.get("/api/agents/payments-ops", headers=ADMIN).json()
    key = _key(client, DEV)
    r = _connect(client, key, _structure("payments-ops", ("admin.delete_everything",)), "evil")
    assert r.status_code == 200
    after = client.get("/api/agents/payments-ops", headers=ADMIN).json()
    for field in ("risk_tier", "environment", "status", "purpose", "registered", "project"):
        assert after[field] == before[field], field
    with session_scope() as s, system_scope("test"):
        caps = s.scalars(select(Capability).where(Capability.tool_key == "admin.delete_everything"))
        assert list(caps) == []


def test_connect_proposes_new_agents_as_drafts_without_grants(client):
    key = _key(client, DEV)
    assert _connect(client, key).status_code == 200
    agent = client.get("/api/agents/shop-agent", headers=ADMIN).json()
    assert agent["status"] == "draft" and agent["registered"] is False
    assert agent["project"] == "shop"
    with session_scope() as s, system_scope("test"):
        row = s.scalar(select(Agent).where(Agent.slug == "shop-agent"))
        identities = list(s.scalars(select(Identity).where(Identity.agent_id == row.id)))
        assert not [c for i in identities for c in i.capabilities]
        entry = s.scalar(
            select(AuditEntry).where(AuditEntry.action == "onboarding.structure.reported")
        )
        assert entry is not None and entry.actor_id == "priya@example.com"
    # Re-running init updates the draft; approving it is a person's call.
    assert _connect(client, key, _structure(tools=("get_order", "refund"))).status_code == 200
    approved = client.post("/api/projects/shop/approve", headers=ADMIN)
    assert approved.status_code == 200 and approved.json()["approved"] == ["shop-agent"]
    agent = client.get("/api/agents/shop-agent", headers=ADMIN).json()
    assert agent["status"] == "active" and agent["registered"] is True
    # A live agent of the same project keeps its review state; new tools are added.
    assert _connect(client, key, _structure(tools=("get_order", "escalate"))).status_code == 200
    agent = client.get("/api/agents/shop-agent", headers=ADMIN).json()
    assert agent["status"] == "active"
    assert {"get_order", "refund", "escalate"} <= set(agent["declared_tools"])


def test_approving_a_project_needs_the_registry_role(client):
    _connect(client, _key(client))
    assert client.post("/api/projects/shop/approve", headers=AUDITOR).status_code == 403


# --- 2. the first load races ----------------------------------------------------------


def test_two_first_loads_at_once_make_one_row(client, monkeypatch):
    from agentfox.capabilities.onboarding import sessions

    real = sessions.find
    raced = {"done": False}

    def stale_find(session, user):
        # Another request inserts the row between this one's read and its insert.
        if not raced["done"]:
            raced["done"] = True
            with session_scope() as other:
                from agentfox.core.tenancy import bind_session

                bind_session(other, user.org_id)
                rid = "onb_raced"
                other.add(
                    OnboardingSession(
                        id=rid,
                        user_id=user.id,
                        org_id=user.org_id,
                        init_key=rid,
                        state=dict(service.INITIAL_STATE),
                        runs={},
                    )
                )
            return None
        return real(session, user)

    monkeypatch.setattr(sessions, "find", stale_find)
    r = client.patch(
        "/api/onboarding/state", json={"currentStep": "test", "completedSteps": []}, headers=ADMIN
    )
    assert r.status_code == 200 and r.json()["currentStep"] == "test"
    with session_scope() as s, system_scope("test"):
        assert len(list(s.scalars(select(OnboardingSession)))) == 1


def test_reading_onboarding_writes_nothing(client):
    for path in (
        "/api/onboarding/state",
        "/api/onboarding/structure",
        "/api/onboarding/guardrails",
        "/api/onboarding/tests?phase=before",
        "/api/onboarding/projects/shop/tests",
    ):
        assert client.get(path, headers=AUDITOR).status_code == 200, path
    with session_scope() as s, system_scope("test"):
        assert list(s.scalars(select(OnboardingSession))) == []


# --- 3. basic guardrails go through simulate-before-enforce ---------------------------


def _basic_modes(client, slug):
    m = client.get(f"/api/agents/{slug}/map", headers=ADMIN).json()
    return {r["mode"] for s in m["stages"] for r in s["rules"] if r["id"].startswith("basic.")}


def test_basic_guardrails_watch_until_simulated(client):
    _connect(client, _key(client))
    r = client.post("/api/onboarding/projects/shop/basic-guardrails", headers=DEV)
    assert r.status_code == 200 and r.json()["added"] == ["shop-agent"]
    assert r.json()["mode"] == "observe"
    assert _basic_modes(client, "shop-agent") == {"observe"}
    tests = client.get("/api/onboarding/projects/shop/tests", headers=ADMIN).json()
    assert tests["basicOn"] is True and tests["basicEnforcing"] is False


def test_basic_guardrails_enforce_for_a_production_role_once_simulated(client):
    from agentfox.platform.policy.model import PolicyDocument

    _connect(client, _key(client))
    doc = service.basic_document("shop-agent")
    client.post(
        "/api/policies/simulate",
        json={"body": PolicyDocument.model_validate(doc.model_dump()).to_yaml()},
        headers=ADMIN,
    )
    r = client.post("/api/onboarding/projects/shop/basic-guardrails", headers=ADMIN)
    assert r.status_code == 200 and r.json()["mode"] == "enforce"
    assert _basic_modes(client, "shop-agent") == {"enforce"}


# --- 4. payloads are validated -------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"structure": {"agents": [{"id": "a"}]}},  # an agent without a name
        {"structure": {"agents": "ab"}},
        {"structure": _structure(), "project": "x" * 121},
        {"structure": {"agents": [], "tools": [{"name": "t", "agentId": 3}]}},
    ],
)
def test_malformed_connect_is_a_422_not_a_500(client, body):
    key = _key(client)
    r = client.post("/api/onboarding/runner/connect", json=body, headers=_bearer(key))
    assert r.status_code == 422, r.text


def test_a_malformed_edit_is_refused(client):
    r = client.put("/api/onboarding/structure", json={"structure": {"agents": "ab"}}, headers=ADMIN)
    assert r.status_code == 422


def test_results_are_capped_at_the_run_size(client):
    key = _key(client)
    _connect(client, key)
    job = client.post("/api/onboarding/runner/poll", headers=_bearer(key)).json()["job"]
    flood = [{"id": f"x-{i}", "type": "prompt_injection", "gotThrough": False} for i in range(1000)]
    r = client.post(
        f"/api/onboarding/runner/runs/{job['runId']}/results",
        json={"results": flood},
        headers=_bearer(key),
    )
    assert r.status_code == 422
    big = [{"id": "y", "type": "prompt_injection", "sentence": "s" * 100_000}]
    r = client.post(
        f"/api/onboarding/runner/runs/{job['runId']}/results",
        json={"results": big},
        headers=_bearer(key),
    )
    assert r.status_code == 422


# --- 5. runs: their own rows, per project, leased ------------------------------------


def test_a_second_project_does_not_take_over_the_first_ones_run(client):
    key = _key(client)
    _connect(client, key, _structure("Alpha Agent"), "alpha")
    _connect(client, key, _structure("Beta Agent"), "beta")
    job = client.post(
        "/api/onboarding/runner/poll", json={"project": "alpha"}, headers=_bearer(key)
    ).json()["job"]
    assert [a["name"] for a in job["structure"]["agents"]] == ["Alpha Agent"]
    alpha = client.get("/api/onboarding/projects/alpha/tests", headers=ADMIN).json()
    assert alpha["first"]["id"] == job["runId"]
    # Each project can be tested from its own map.
    assert client.get("/api/onboarding/projects/beta/tests", headers=ADMIN).json()["first"]


def test_a_dead_runner_does_not_block_the_project_for_ever(client):
    key = _key(client)
    _connect(client, key)
    job = client.post("/api/onboarding/runner/poll", headers=_bearer(key)).json()["job"]
    assert client.post("/api/onboarding/projects/shop/tests", headers=ADMIN).status_code == 409
    with session_scope() as s, system_scope("test"):
        s.get(OnboardingRun, job["runId"]).lease_expires_at = utcnow() - dt.timedelta(seconds=1)
    shown = client.get(f"/api/onboarding/tests/{job['runId']}", headers=ADMIN).json()
    assert shown["status"] == "failed" and "stopped" in shown["error"]
    assert client.post("/api/onboarding/projects/shop/tests", headers=ADMIN).status_code == 200


def test_results_after_a_run_finished_are_refused(client):
    key = _key(client)
    _connect(client, key)
    job = client.post("/api/onboarding/runner/poll", headers=_bearer(key)).json()["job"]
    url = f"/api/onboarding/runner/runs/{job['runId']}/results"
    done = {"results": [{"id": "a", "type": "prompt_injection"}], "done": True}
    assert client.post(url, json=done, headers=_bearer(key)).status_code == 200
    late = client.post(url, json={"error": "boom"}, headers=_bearer(key))
    assert late.status_code == 409
    shown = client.get(f"/api/onboarding/tests/{job['runId']}", headers=ADMIN).json()
    assert shown["status"] == "done"


# --- 6. the client keeps results until they are delivered -----------------------------


def test_the_client_keeps_results_it_could_not_send():
    from agentfox.capabilities.onboarding.client import _Results

    class Flaky:
        def __init__(self):
            self.fail = True
            self.sent = []

        def post(self, path, body=None):
            if self.fail:
                raise RuntimeError("network down")
            self.sent.append(body)
            return {"ok": True}

    api = Flaky()
    out = _Results(api, "run_1")
    out.add({"id": "a"})
    assert out.flush() is False
    api.fail = False
    assert out.flush() is True
    assert api.sent[0]["results"] == [{"id": "a"}]
    assert out.flush(done=True) is True and api.sent[-1] == {"results": [], "done": True}


# --- 7. model errors name the right provider ------------------------------------------


def test_model_errors_name_the_provider():
    anthropic = (
        "anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': "
        "{'type': 'invalid_request_error', 'message': 'Your credit balance is too low to "
        "access the Anthropic API.'}}"
    )
    said = runner_mod.explain_model_error(anthropic)
    assert "Anthropic" in said and "OpenAI" not in said and "credit" in said

    openai = "openai.RateLimitError: Error code: 429 - {'error': {'code': 'insufficient_quota'}}"
    said = runner_mod.explain_model_error(openai)
    assert "OpenAI" in said and "credits" in said

    # A 401 in an order number is not a bad key.
    said = runner_mod.explain_model_error("ValueError: order 401-77 not found")
    assert "API key" not in said
    said = runner_mod.explain_model_error("anthropic.AuthenticationError: invalid x-api-key")
    assert "API key" in said and "Anthropic" in said


def test_init_does_not_claim_agents_were_set_up_when_none_were_found(tmp_path, monkeypatch):
    """Found running init in an empty folder: it said 'Connected. Your agents are set
    up' with 0 agents, and 'this folder has no other files were present'."""
    from io import StringIO

    from rich.console import Console

    from agentfox.capabilities.onboarding import client as init_client

    sent = []

    def post(self, path, body=None):
        sent.append(path)
        if path == "/runner/poll":  # after connecting it polls for tests: stop there
            raise KeyboardInterrupt
        return {}

    monkeypatch.setattr(init_client._Api, "post", post)
    out = StringIO()
    console = Console(file=out, width=200)
    init_client.connect("afi_test", "http://127.0.0.1:1", path=tmp_path, console=console)
    text = out.getvalue()
    assert "/runner/connect" in sent
    assert "Your agents are set up" not in text
    assert "no agents were found" in text
    assert "has no other files were present" not in text
