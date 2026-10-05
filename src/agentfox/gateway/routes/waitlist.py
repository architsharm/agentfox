"""Hosted-cloud waitlist — the one public write endpoint.

Unauthenticated by design, like `playground.py`: the whole point is that the person
submitting has no account, because a waitlist is the thing you join *before* there is
anything to sign in to. Until this existed the pricing page offered a `mailto:`,
which is not a waitlist — it is a hope that somebody keeps a list in their inbox.

What keeps a public write safe to expose:

  * It writes one row to one table and reads nothing else. `waitlist_signups` holds
    no tenant's data (see the model's docstring for why it sits outside the tenant
    pattern), so there is nothing here to read across a boundary and no boundary to
    cross.
  * It calls nothing. No mail is sent, no CRM is notified, no third party is told.
    That is a deliberate constraint, not a gap to close later: the moment this posts
    an address to somebody else's API, a stranger's email leaves the deployment on
    the strength of an unauthenticated request, and the endpoint stops being a form
    and becomes a relay. Somebody reads the table when there is something to announce.
  * The unique index on the email is what makes a repeat submit a no-op, so retries
    and double-clicks cost a query rather than filling the table with the same person.
  * It is rate limited per address with the same limiter the playground uses, so it
    cannot be turned into a way to fill a disk.

The response is deliberately the same shape whether the address was new or already
present. Answering "you are already on this list" to an unauthenticated caller would
turn the endpoint into an oracle for whether a given person has signed up; the
`status` field distinguishes the two only so the page can say "welcome back" rather
than being wrong, and it is the one thing here worth revisiting if that ever matters
more than the wording.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentfox.core.models import WaitlistSignup
from agentfox.gateway.deps import db

# The limiter class lives in `playground_sessions` because that is where the first
# public endpoint needed one. Importing it rather than writing a second one is the
# point: two rate limiters with two sets of semantics is how one of them ends up
# quietly not working. Its limits are per process — see the class docstring for what
# that does and does not bound on a serverless deployment.
from agentfox.gateway.playground_sessions import RateLimiter

router = APIRouter(tags=["waitlist"])

#: Signups per client address. A person fills this in once; the allowance is loose
#: enough for a shared office NAT and a few typos, tight enough that the endpoint is
#: not a way to write unbounded rows.
waitlist_limiter = RateLimiter(limit=10, window_seconds=3600)

#: Deliberately not an RFC 5322 parser. A validating regex for that grammar is a
#: famous several-hundred-character expression that still accepts addresses no mail
#: server will route, and the only thing that actually proves an address works is
#: sending to it — which this endpoint does not do. So the bar here is "is this
#: plausibly an address, or did somebody paste a sentence", and the cost of being
#: wrong is one junk row rather than a rejected real customer.
_PLAUSIBLE_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

#: What `source` may look like. Constrained because it is written by whoever posts
#: the form and read back by an operator doing `WHERE source = ...`; a value that is
#: a slug and nothing else keeps that query honest.
_SOURCE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class WaitlistRequest(BaseModel):
    """What the pricing form posts. Everything but the address is optional."""

    email: str = Field(max_length=320)
    #: Which list. Defaults to the only one that exists, so the pricing form does not
    #: have to send it and a future second form can.
    source: str = "hosted-cloud"
    company: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        """Lowercase and strip *here*, so the unique index sees one canonical form.

        Doing it in the validator rather than in the handler means every caller of
        this model gets it, including any future one that does not remember that
        `Ada@Example.com ` and `ada@example.com` have to be the same row.
        """
        normalized = value.strip().lower()
        if not _PLAUSIBLE_EMAIL.match(normalized):
            raise ValueError("that does not look like an email address")
        return normalized

    @field_validator("source")
    @classmethod
    def _check_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SOURCE.match(normalized):
            raise ValueError("source must be a lowercase slug")
        return normalized

    @field_validator("company", "note")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        """An empty form field is an unanswered question, not an answer of ""."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


def _client_key(request: Request) -> str:
    """The address the limiter counts against.

    `request.client.host`, matching `playground.py` — deliberately not
    `X-Forwarded-For`, which is a header the client sets and can therefore rotate to
    defeat the limit unless a proxy is known to overwrite it. Behind a proxy this
    counts every visitor as one address, which fails closed (too strict) rather than
    open, and the cap is sized with that in mind.
    """
    return request.client.host if request.client else "unknown"


@router.post("/api/waitlist", summary="Join the hosted-cloud waitlist")
def join_waitlist(
    request: Request,
    payload: WaitlistRequest,
    session: Session = Depends(db),
) -> dict[str, Any]:
    """Record an address. Unauthenticated, idempotent, and it sends nothing anywhere.

    Submitting the same address twice succeeds both times. That is not politeness: a
    form post that answers 409 to a browser retry shows a stranger an error for
    something that worked, and the row they are being told conflicts with is their
    own.
    """
    if not waitlist_limiter.check(_client_key(request)):
        raise HTTPException(
            429,
            "Too many waitlist signups from this address recently — please try again in a while.",
        )

    # No `system_scope` and no tenant binding: `WaitlistSignup` is not `TenantScoped`,
    # so the session-level filter never attaches a predicate to this query in the
    # first place. See the model's docstring.
    existing = session.scalar(select(WaitlistSignup).where(WaitlistSignup.email == payload.email))
    if existing is None:
        try:
            # A savepoint, so losing a race to a concurrent submit of the same address
            # rolls back only this insert and not anything else on the session. The
            # unique index, not the SELECT above, is what actually decides it — the
            # check-then-insert on its own is a race, and this is the losing branch.
            with session.begin_nested():
                session.add(
                    WaitlistSignup(
                        email=payload.email,
                        source=payload.source,
                        company=payload.company,
                        note=payload.note,
                    )
                )
                session.flush()
        except IntegrityError:
            existing = session.scalar(
                select(WaitlistSignup).where(WaitlistSignup.email == payload.email)
            )
            if existing is None:  # pragma: no cover - the index says this cannot happen
                raise

    return {
        "status": "already_on_list" if existing is not None else "added",
        "email": payload.email,
        "source": payload.source,
        "message": (
            "You're already on the list — we'll email you when hosted AgentFox opens."
            if existing is not None
            else "You're on the list. We'll email you when hosted AgentFox opens."
        ),
    }
