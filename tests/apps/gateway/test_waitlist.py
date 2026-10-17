"""The hosted-cloud waitlist: a public, unauthenticated write
(gateway/routes/waitlist.py, models.WaitlistSignup).

Three properties are worth pinning down here, and they are the three that make a
public write endpoint safe to leave on the internet:

  * it takes no credential, because the person joining does not have one yet;
  * a repeat submit is a no-op, because a browser retry must not be an error and
    must not be a second row;
  * the row lands outside tenant isolation on purpose, and `test_tenancy.py` is
    where that exemption is held to its roster.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from agentfox.core.db import session_scope
from agentfox.core.models import WaitlistSignup


@pytest.fixture(autouse=True)
def _reset_waitlist_rate_limit():
    """The limiter is a process-global singleton by design (it bounds abuse across
    the whole gateway process, not per request). Reset between tests so one test's
    budget does not bleed into the next; a real deployment never resets mid-run."""
    from agentfox.apps.gateway.routes.waitlist import waitlist_limiter

    waitlist_limiter._hits.clear()
    yield


def _rows() -> list[WaitlistSignup]:
    with session_scope() as session:
        return list(session.scalars(select(WaitlistSignup).order_by(WaitlistSignup.created_at)))


def test_signing_up_records_the_address(client):
    resp = client.post(
        "/api/waitlist",
        json={"email": "ada@example.com", "company": "Analytical Engines", "note": "EU region?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "added"
    assert body["email"] == "ada@example.com"
    assert body["source"] == "hosted-cloud"
    assert body["message"]

    (row,) = _rows()
    assert row.email == "ada@example.com"
    assert row.source == "hosted-cloud"
    assert row.company == "Analytical Engines"
    assert row.note == "EU region?"
    assert row.id.startswith("wlt_")


def test_the_stored_address_is_lowercased_and_stripped(client):
    """Otherwise ` Ada@Example.com ` and `ada@example.com` are two rows and one
    person, and the unique index that makes the endpoint idempotent never fires."""
    resp = client.post("/api/waitlist", json={"email": "  Ada@Example.COM  "})
    assert resp.status_code == 200
    assert resp.json()["email"] == "ada@example.com"
    assert [r.email for r in _rows()] == ["ada@example.com"]


def test_submitting_the_same_address_twice_is_idempotent(client):
    """A double-clicked submit or a browser retry must succeed, not 409 and not 500.
    The conflicting row is the visitor's own; telling them it is a conflict is telling
    them their own signup failed."""
    first = client.post("/api/waitlist", json={"email": "ada@example.com"})
    second = client.post("/api/waitlist", json={"email": "ADA@example.com "})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "added"
    assert second.json()["status"] == "already_on_list"
    assert second.json()["email"] == "ada@example.com"

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(WaitlistSignup)) == 1


@pytest.mark.parametrize(
    "email",
    [
        "not-an-email",
        "",
        "   ",
        "ada@localhost",  # no dot in the domain: plausible on a LAN, not on the internet
        "ada example@com",
        "@example.com",
        "ada@",
        "two@addresses@example.com",
        "a" * 400 + "@example.com",
    ],
)
def test_obvious_rubbish_is_rejected(client, email):
    """Deliberately not an RFC 5322 conformance suite — the endpoint does not claim
    to know which addresses deliver, only that a sentence is not an address."""
    resp = client.post("/api/waitlist", json={"email": email})
    assert resp.status_code == 422
    assert _rows() == []


def test_it_needs_no_authentication(client):
    """The point of the endpoint. A waitlist is what you join *before* you have an
    account, so a signup that required a session could never be used by the only
    people it is for.

    Asserted two ways, because "it worked without a header" is weak on its own: the
    handler declares no `current_user` dependency at all, and a credential that a
    real control-plane route rejects outright does not change the answer here — the
    route never looks.
    """
    import inspect

    from fastapi import params

    from agentfox.apps.gateway.deps import current_user
    from agentfox.apps.gateway.routes.waitlist import join_waitlist, router

    declared = [
        p.default.dependency
        for p in inspect.signature(join_waitlist).parameters.values()
        if isinstance(p.default, params.Depends)
    ]
    assert current_user not in declared
    assert not router.dependencies

    assert client.post("/api/waitlist", json={"email": "ada@example.com"}).status_code == 200

    # A revoked-looking API token: the same header on a control-plane route is a 401,
    # so the 200 below is the waitlist not looking at credentials rather than the test
    # client being trusted. (A *missing* header would prove nothing here — this
    # deployment's development-identity fallback accepts that on every route.)
    bad = {"Authorization": "Bearer nom_api_definitely-not-a-token"}
    assert client.get("/api/agents", headers=bad).status_code == 401
    signup = client.post("/api/waitlist", json={"email": "grace@example.com"}, headers=bad)
    assert signup.status_code == 200


def test_the_source_field_separates_one_list_from_the_next(client):
    """`source` is what stops the second waitlist from being a second table."""
    client.post("/api/waitlist", json={"email": "ada@example.com"})
    client.post("/api/waitlist", json={"email": "grace@example.com", "source": "on-prem-beta"})
    assert {r.email: r.source for r in _rows()} == {
        "ada@example.com": "hosted-cloud",
        "grace@example.com": "on-prem-beta",
    }


def test_a_source_that_is_not_a_slug_is_rejected(client):
    """It is read back by an operator running `WHERE source = ...`; free text written
    by whoever posts the form would make that query a guess."""
    resp = client.post(
        "/api/waitlist", json={"email": "ada@example.com", "source": "'; DROP TABLE --"}
    )
    assert resp.status_code == 422
    assert _rows() == []


def test_one_address_cannot_fill_the_table(client):
    """Same per-IP limiter the playground uses. Without it the only public write in
    the app is an unbounded one."""
    from agentfox.apps.gateway.routes.waitlist import waitlist_limiter

    for i in range(waitlist_limiter.limit):
        assert client.post("/api/waitlist", json={"email": f"a{i}@example.com"}).status_code == 200
    over = client.post("/api/waitlist", json={"email": "one-too-many@example.com"})
    assert over.status_code == 429
    assert len(_rows()) == waitlist_limiter.limit


def test_it_sends_nothing_anywhere(client, monkeypatch):
    """Storage only. The constraint is in the module docstring and this is the test
    that keeps it true: the moment a signup posts an address to a third party, an
    unauthenticated request is what makes a stranger's email leave the deployment.

    Checked at the socket, not at one HTTP library, so it catches a call made through
    whichever client somebody reaches for. The test client speaks ASGI in-process and
    the database is a file, so nothing legitimate on this path opens one.
    """
    import socket

    def _forbidden(*_a, **_k):  # pragma: no cover - only runs if the rule is broken
        raise AssertionError("the waitlist endpoint must not call out")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)

    assert client.post("/api/waitlist", json={"email": "ada@example.com"}).status_code == 200
    assert len(_rows()) == 1
