"""Tables that sit at the edge of the tenant model: the public playground and the
hosted-cloud waitlist.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from agentfox.core import ids
from agentfox.core.models.base import Base, TenantExempt, TimestampMixin, utcnow


class PlaygroundSandbox(Base, TimestampMixin):
    """The registry row for one public-playground sandbox.

    A sandbox is a tenant. Its ``org_id`` is its own id, and every row the visitor's
    activity produces (traces, decisions, findings, audit entries, the seeded demo
    fixtures) is written under that org, so the ordinary session-level tenant filter in
    ``tenancy.py`` is what keeps one sandbox out of another. No sandbox-specific filter
    exists, because a filter somebody has to remember is not a control.

    This row is what makes a sandbox outlive the process that created it: before it
    existed, sandboxes lived in a module-level dict with a per-sandbox in-memory SQLite
    engine, which works on one long-lived container and does not work at all on the
    serverless deployment in ``api/vercel.json``, where the next request is a different
    instance and finds nothing.

    What the id proves and does not prove: the id is a 128-bit random value and it is
    the only credential the playground has, so holding it is what grants access. It
    does not identify a person and it is not revocable. Anyone the visitor sends the
    link to can read the sandbox.
    """

    __tablename__ = "playground_sandboxes"

    #: Also this sandbox's ``org_id``. Format is checked before it is ever bound to a
    #: session, so a caller cannot name a real tenant in the path and be bound to it.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: Idle expiry. Extended on each use, so the TTL the page shows is time since the
    #: visitor's last action, not time since creation.
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    #: Trace ids this sandbox produced, oldest first, capped. Stored rather than
    #: recomputed so the live sidebar shows the visitor's own actions in the order they
    #: happened and not the seeded fixtures' traces.
    trace_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class WaitlistSignup(Base, TenantExempt):
    """A stranger asking to be told when the hosted service exists.

    Why this sits outside the tenant pattern that governs every other table: a
    waitlist signup happens *before* the person has an org. Scoping it would mean
    inventing a tenant for somebody who has not signed up for anything, and then
    either hiding the list from the operator who needs to read it or filing every
    signup under the deployment's own org — a tenant boundary that means nothing,
    which is worse than admitting there isn't one. So the row belongs to nobody, and
    :class:`TenantExempt` plus :data:`TENANT_EXEMPT_TABLES` say so out loud.

    The consequence to hold in mind: ``tenancy.py``'s session filter does not touch
    this table, so a query here returns every signup whatever tenant the session is
    bound to. That is correct for a list of people who have no tenant, and it is the
    reason nothing tenant-facing may ever be added to this table.

    The email is unique, stored lowercased and stripped, so somebody double-clicking
    the submit button joins the list once rather than twice. ``source`` is what keeps
    this table usable for the *next* list — it names which form the person came
    through, so "hosted cloud" and whatever is asked in a year are one table and one
    endpoint rather than two of each.

    What is deliberately absent: nothing here sends mail, and no third party is told.
    A signup is a row. Someone reads the table when there is something to announce.
    """

    __tablename__ = "waitlist_signups"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.waitlist_signup_id)
    #: Unique across the whole table, not per anything — see the class docstring. 320
    #: is the longest address SMTP will carry (64 local + @ + 255 domain).
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    #: Which list this is. Indexed because reading "everyone waiting for hosted cloud"
    #: is the only query this table has.
    source: Mapped[str] = mapped_column(String(64), default="hosted-cloud", index=True)
    #: Both optional, both free text the visitor typed. Kept because "who is asking"
    #: is the only thing that makes a waitlist worth more than a count.
    company: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    #: Declared here rather than inherited: ``TimestampMixin`` carries ``TenantScoped``
    #: with it, which is exactly what this table must not have.
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
