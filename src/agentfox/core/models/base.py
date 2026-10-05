"""The declarative base, the tenancy mixins every model inherits, and the import-time
check that no model escapes tenant isolation.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def as_aware(value: dt.datetime | None) -> dt.datetime | None:
    """Attach UTC to a datetime that lost its timezone in storage.

    SQLite has no timezone type, so a value written as aware comes back naive and
    comparing it to :func:`utcnow` raises. That turned every credential *with an
    expiry* into a 500 on the inline path — invisible until agent credentials were
    actually resolved there, because nothing else read the field.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, list[Any]: JSON}


class TenantScoped:
    """Carries the tenant key, and is the hook every isolation filter targets.

    Isolation is applied against *this class*, so inheriting it is what makes a model
    tenant-safe — and :func:`agentfox.core.tenancy.assert_tenant_safe` fails at import if
    any mapped class does not. That inverts the usual arrangement: instead of
    remembering to filter each new query, you cannot define a model that escapes the
    filter in the first place.
    """

    org_id: Mapped[str] = mapped_column(String(64), default="org_default", index=True)


class TenantExempt:
    """Marks the rare table that exists *before* there is a tenant to scope it to.

    The rule in :class:`TenantScoped` is the important one and this does not soften
    it: a model that simply forgets tenancy still fails at import. What this adds is
    a way to say "outside the tenant model, on purpose" that is impossible to do by
    accident — inheriting this mixin is not enough on its own, the table must also be
    named in :data:`TENANT_EXEMPT_TABLES` below, so the exemption cannot be granted
    without editing the one place that states the bar for granting it.

    The bar: a row here is readable by every tenant and by none, because no tenant
    filter applies to it. So the only rows that may live in such a table are rows that
    belong to *nobody* — never a customer's data under a different name.
    """


#: Tables allowed to sit outside tenant isolation, and why each one is allowed.
#:
#: Read this list as a security review: every entry is a table the filter in
#: ``tenancy.py`` does not touch. It is deliberately a hard-coded roster rather than
#: "whatever inherits the mixin", so adding a table to it is a diff a reviewer sees.
TENANT_EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        # A waitlist signup is a stranger asking to be told when the hosted service
        # exists. There is no org to scope it to yet — creating one would be inventing
        # a tenant for someone who has not signed up for anything.
        "waitlist_signups",
    }
)


class TimestampMixin(TenantScoped):
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


def _is_exempt(cls: type) -> bool:
    """True for a mapped class deliberately placed outside tenant isolation.

    Both halves have to hold — the mixin *and* the roster entry — so neither a stray
    inheritance nor a stray list entry is enough on its own.
    """
    return (
        issubclass(cls, TenantExempt)
        and getattr(cls, "__tablename__", None) in TENANT_EXEMPT_TABLES
    )


def _assert_every_model_is_tenant_scoped() -> None:
    """Fail loudly at import if a model escapes tenant isolation.

    Tenant filtering targets :class:`TenantScoped`, so a model that does not inherit it
    is invisible to the filter and its rows are readable by every tenant. That is a
    data breach, and it is the kind introduced by someone adding a table months from
    now who has never read the tenancy module. Making it an import error means the
    mistake cannot reach a running system.
    """
    escaped = sorted(
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if not issubclass(mapper.class_, TenantScoped)
        and not issubclass(mapper.class_, TenantExempt)
    )
    if escaped:
        raise RuntimeError(
            "these models are not tenant-scoped and would leak across tenants: "
            f"{escaped}. Inherit TenantScoped (usually via TimestampMixin)."
        )

    # The other direction, and the reason the roster is a roster: a model that wears
    # the exemption mixin but is not on the list is somebody opting a table out of
    # tenancy without going near the list that explains what that costs. Checked
    # separately from the sweep above so this case gets its own message — told to
    # "inherit TenantScoped", the author of such a model would go looking for a bug
    # that isn't there.
    unlisted = sorted(
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantExempt)
        and mapper.class_.__tablename__ not in TENANT_EXEMPT_TABLES
    )
    if unlisted:
        raise RuntimeError(
            f"these models claim TenantExempt but are not listed in "
            f"TENANT_EXEMPT_TABLES: {unlisted}. Add the table name there, in the same "
            "diff, with the reason it holds no tenant's data."
        )
