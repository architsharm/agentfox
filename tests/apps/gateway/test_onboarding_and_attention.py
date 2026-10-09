"""The start checklist and the attention list say what is actually true.

Two ways they did not:

* "Turn enforcement on" ticked as soon as any decision had been recorded in enforce
  mode. The shipped tool-containment pack enforces from the first call, so the step
  read as done on day one while baseline — the policy the step is about — was still
  only observing.
* A draft agent proposed by a repo scan is unregistered by construction, and the
  attention list raised it as a high-severity "running and was never registered"
  item. It never ran; it is waiting for review, which the agents page already shows.
"""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def _step(client, step_id: str) -> dict:
    body = client.get("/api/onboarding", headers=ADMIN).json()
    return next(s for s in body["steps"] if s["id"] == step_id)


def test_enforce_step_is_not_done_while_baseline_observes(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Decision
    from agentfox.platform.policy.store import active_layers

    with session_scope() as session:
        modes = {layer.document.key: layer.document.mode for layer in active_layers(session)}
        assert modes.get("baseline") == "observe"
        # What tool containment produces from the first call.
        session.add(
            Decision(surface="tool_call", tool_key="refund", mode="enforce", verdict="block")
        )

    assert _step(client, "enforce")["done"] is False


def test_enforce_step_is_done_once_baseline_enforces(client):
    from agentfox.core.db import session_scope
    from agentfox.platform.policy.store import set_mode

    with session_scope() as session:
        set_mode(session, "baseline", "enforce")

    assert _step(client, "enforce")["done"] is True


def test_a_scan_proposed_draft_is_not_an_unregistered_agent(client):
    from agentfox.core.db import session_scope
    from agentfox.platform.registry.service import register_agent

    with session_scope() as session:
        register_agent(session, slug="scan-found-bot", draft=True)

    body = client.get("/api/attention", headers=ADMIN).json()
    assert not [i for i in body["items"] if i["subject"] == "scan-found-bot"]


def test_an_agent_seen_in_traffic_without_registration_still_is(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    with session_scope() as session:
        session.add(Agent(slug="ghost-bot", registered=False, status="active"))

    body = client.get("/api/attention", headers=ADMIN).json()
    shadow = [i for i in body["items"] if i["subject"] == "ghost-bot"]
    assert shadow and shadow[0]["kind"] == "shadow_agent"


# ---------------------------------------------------------------------------
# Get started is the page a new user waits on
# ---------------------------------------------------------------------------


def _statements(fn) -> list[str]:
    """Run ``fn`` and return the SQL statements it sent."""
    from sqlalchemy import event

    from agentfox.core.db import get_engine

    seen: list[str] = []

    def record(conn, cursor, statement, *rest):  # noqa: ARG001
        seen.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return seen


def test_the_checklist_counts_are_one_round_trip(client):
    """Each count was its own statement, and against a remote database the round
    trips, not the counting, were what the page waited on."""
    client.get("/api/onboarding", headers=ADMIN)  # first call may provision the caller
    me = _statements(lambda: client.get("/api/me", headers=ADMIN))
    sent = _statements(lambda: client.get("/api/onboarding", headers=ADMIN))
    # /api/me is authentication plus one lookup. Onboarding is authentication, the
    # counts, and the list of agent ids for the agent picker: one more, not eleven.
    assert len(sent) <= len(me) + 1


def test_the_combined_counts_stay_inside_the_tenant(isolated_db):
    from agentfox.apps.gateway.routes.onboarding import _onboarding_counts
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Trace
    from agentfox.core.tenancy import tenant

    for org, n in (("org_acme", 1), ("org_globex", 3)):
        with tenant(org), session_scope() as session:
            for i in range(n):
                session.add(Agent(slug=f"{org}-{i}", name="a", environment="production"))
                session.add(Trace(agent_slug=f"{org}-{i}"))

    with tenant("org_acme"), session_scope() as session:
        counts = _onboarding_counts(session)
    assert counts["agents"] == 1
    assert counts["traces"] == 1


def test_large_tables_are_counted_up_to_a_cap(isolated_db, monkeypatch):
    from agentfox.apps.gateway.routes import onboarding as mod
    from agentfox.core.db import session_scope
    from agentfox.core.models import Trace

    monkeypatch.setattr(mod, "COUNT_CAP", 3)
    with session_scope() as session:
        for _ in range(5):
            session.add(Trace(agent_slug="busy"))
    with session_scope() as session:
        assert mod._onboarding_counts(session)["traces"] == 3


def test_the_repo_list_is_reused_briefly(client, monkeypatch):
    """Listing repositories is a call to GitHub, and Connections made it on every
    visit. Which of them were already scanned is still read fresh."""
    import httpx
    from cryptography.fernet import Fernet
    from sqlalchemy import select

    from agentfox.apps.gateway.routes import integrations
    from agentfox.core.config import get_settings
    from agentfox.core.db import session_scope
    from agentfox.core.models import GithubConnection, ScanRun, User

    monkeypatch.setattr(get_settings(), "token_encryption_key", Fernet.generate_key().decode())
    with session_scope() as session:
        user = session.scalars(select(User)).first()
        session.add(
            GithubConnection(
                github_user_id="1",
                github_login="octo",
                access_token_encrypted=integrations._encrypt("gho_test"),
                connected_by_user_id=user.id,
            )
        )
        session.add(ScanRun(repo_full_name="octo/one"))
        session.add(ScanRun(repo_full_name="octo/one"))

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return httpx.Response(
            200,
            json=[
                {"full_name": "octo/one", "private": False, "default_branch": "main"},
                {"full_name": "octo/two", "private": True, "default_branch": "dev"},
            ],
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(integrations.httpx, "get", fake_get)
    integrations._repo_cache.clear()
    first = client.get("/api/integrations/github/repos", headers=ADMIN).json()
    second = client.get("/api/integrations/github/repos", headers=ADMIN).json()
    assert len(calls) == 1
    assert first == second
    assert {r["full_name"]: r["scanned"] for r in first["repos"]} == {
        "octo/one": True,
        "octo/two": False,
    }
