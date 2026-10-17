"""The posture an admin chooses in the product, clamped by what the deployment permits.

Two things in this package have been called "configuration", and keeping them apart is
the entire job of this module.

**Deployment settings** — ``AGENTFOX_ALLOW_EGRESS``, API keys, base URLs — are chosen
by whoever runs the process. They are read once into a cached
:class:`~agentfox.core.config.Settings`, they are process-global, and no HTTP request can
change them. **Posture** is the governance choice an admin makes inside the product:
which of the permitted tiers to actually use, what happens when the payload contains
personal data, whether a remote outage denies the request or is treated as no signal.

The relationship between them is one-directional and enforced here:

    *Posture may only narrow what deployment permits. It may never widen it.*

Enabling JEV in the dashboard on a deployment whose ``allow_egress`` is off is
**refused**, not stored and silently ignored. The distinction matters more than it
looks: a posture page that displays JEV as enabled while nothing is in fact being sent
to JEV has answered a compliance question wrongly, in writing, in a screenshot somebody
will later attach to an attestation. A refusal is a worse afternoon and a better record.

Why this is not simply more fields on ``Settings``: ``get_settings()`` is
``lru_cache``'d and process-global, so making it writable from a request would let one
tenant's egress choice change another tenant's behaviour in the same process. Posture is
a tenant-scoped row, resolved per request, and the deployment ceiling is the thing that
is global — which is the correct way round, because the ceiling is the part that was
set by the person who accepted the risk.

Resolution outside a request: :func:`effective` falls back to the deployment settings
when no posture has been activated. A CLI run or a library embedding uses the deployment
settings alone, which is what keeps the benchmarks comparable.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from agentfox.capabilities.judgment.capability import EGRESS_TIERS, Tier
from agentfox.capabilities.judgment.egress import Backend, PiiEgress

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime, types only
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


class PostureRefused(ValueError):
    """A posture change was rejected because it would widen the deployment ceiling.

    A ``ValueError`` so the route maps it to a 4xx the same way every other rejected
    write in the gateway is mapped, rather than inventing a second error protocol for
    the one surface where the rejection matters most.
    """


#: How strict each PII choice is. Higher is stricter; posture may move up, never down.
_PII_RANK: dict[PiiEgress, int] = {PiiEgress.ALLOW: 0, PiiEgress.REDACT: 1, PiiEgress.BLOCK: 2}

#: Backends that mean "a third party may see the payload".
_REMOTE_BACKENDS = frozenset({Backend.REMOTE, Backend.AUTO})


@dataclass(frozen=True)
class Posture:
    """What is turned on, as a value rather than a scattering of settings lookups."""

    tiers: frozenset[Tier] = frozenset({Tier.DETERMINISTIC})
    pii_egress: PiiEgress = PiiEgress.REDACT
    fail_closed: bool = True
    backend: Backend = Backend.LOCAL
    #: Bumped on every write; the version an auditor quotes.
    version: int = 0

    def __post_init__(self) -> None:
        # DETERMINISTIC is not a choice. It needs no key, no weights and no network,
        # and a kind left with no permitted decider is not a posture anyone meant.
        object.__setattr__(self, "tiers", frozenset(self.tiers) | {Tier.DETERMINISTIC})

    @property
    def egress_tiers(self) -> frozenset[Tier]:
        """The enabled tiers that send the payload off this machine."""
        return self.tiers & EGRESS_TIERS

    @property
    def sends_anything(self) -> bool:
        return bool(self.egress_tiers) or self.backend in _REMOTE_BACKENDS

    def to_json(self) -> dict[str, Any]:
        return {
            "tiers": sorted(str(t) for t in self.tiers),
            "pii_egress": str(self.pii_egress),
            "fail_closed": self.fail_closed,
            "backend": str(self.backend),
            "version": self.version,
        }


@dataclass(frozen=True)
class Ceiling:
    """What the deployment permits — the upper bound on any posture.

    Read from settings, never from the database, because the whole point is that it is
    not reachable from a request.
    """

    allow_egress: bool = False
    #: The loosest PII handling the deployment will accept.
    pii_egress: PiiEgress = PiiEgress.REDACT
    #: When true, posture may not turn failing-closed off.
    fail_closed: bool = True

    @classmethod
    def from_settings(cls, settings: object | None = None) -> Ceiling:
        if settings is None:
            from agentfox.core.config import get_settings

            settings = get_settings()
        return cls(
            allow_egress=bool(getattr(settings, "allow_egress", False)),
            pii_egress=_as_pii(getattr(settings, "judgment_pii_egress", "redact")),
            fail_closed=bool(getattr(settings, "judgment_fail_closed", True)),
        )

    def permits_pii(self, value: PiiEgress) -> bool:
        """Whether posture may choose this personal-data handling.

        Public because the settings UI has to render the unavailable options as
        disabled-with-a-reason rather than omit them: a control that is simply absent
        teaches an operator the product cannot do it.
        """
        return _PII_RANK[value] >= _PII_RANK[self.pii_egress]

    def permits_tier(self, tier: Tier) -> bool:
        """Whether posture may enable this tier at all."""
        return self.allow_egress or tier not in EGRESS_TIERS

    def refusals(self, posture: Posture) -> list[str]:
        """Every reason this posture exceeds the ceiling, in the operator's words.

        All of them rather than the first: an admin fixing one refusal only to meet the
        next is how a configuration page teaches people to stop reading the errors.
        """
        out: list[str] = []
        if not self.allow_egress and posture.egress_tiers:
            names = ", ".join(sorted(str(t) for t in posture.egress_tiers))
            out.append(
                f"tier(s) {names} send the payload to a third party, and this "
                "deployment has egress switched off (AGENTFOX_ALLOW_EGRESS). "
                "That is set by whoever runs the process, not from here."
            )
        if not self.allow_egress and posture.backend in _REMOTE_BACKENDS:
            out.append(
                f"backend '{posture.backend}' reaches a remote service, and this "
                "deployment has egress switched off (AGENTFOX_ALLOW_EGRESS)."
            )
        if _PII_RANK[posture.pii_egress] < _PII_RANK[self.pii_egress]:
            out.append(
                f"pii_egress '{posture.pii_egress}' is looser than the deployment's "
                f"'{self.pii_egress}'. Posture may only tighten how personal data is "
                "handled; loosening it is a deployment decision."
            )
        if self.fail_closed and not posture.fail_closed:
            out.append(
                "this deployment requires judgment to fail closed "
                "(AGENTFOX_JUDGMENT_FAIL_CLOSED), so posture may not make an outage "
                "silently permissive."
            )
        return out

    def clamp(self, posture: Posture) -> Posture:
        """The strictest posture at or below this ceiling — for *reads*, never writes.

        A write that exceeds the ceiling is refused, because the admin is present and
        can be told. A read clamps instead, because the row may predate a deployment
        that has since revoked egress, and the honest answer to "what is in force now"
        is the narrowed one rather than what someone chose last year.
        """
        tiers = posture.tiers
        backend = posture.backend
        if not self.allow_egress:
            tiers = tiers - EGRESS_TIERS
            if backend in _REMOTE_BACKENDS:
                backend = Backend.LOCAL
        pii = posture.pii_egress
        if _PII_RANK[pii] < _PII_RANK[self.pii_egress]:
            pii = self.pii_egress
        fail_closed = posture.fail_closed or self.fail_closed
        return replace(
            posture, tiers=tiers, backend=backend, pii_egress=pii, fail_closed=fail_closed
        )


# --- Reading what the deployment alone says --------------------------------


def from_settings(settings: object | None = None) -> Posture:
    """The posture implied by settings alone — what applies before anyone edits one."""
    if settings is None:
        from agentfox.core.config import get_settings

        settings = get_settings()
    tiers = set()
    for name in getattr(settings, "judgment_tiers", None) or []:
        try:
            tiers.add(Tier(str(name).strip().lower()))
        except ValueError:
            log.warning("ignoring unknown judgment tier %r in settings", name)
    return Posture(
        tiers=frozenset(tiers),
        pii_egress=_as_pii(getattr(settings, "judgment_pii_egress", "redact")),
        fail_closed=bool(getattr(settings, "judgment_fail_closed", True)),
        backend=_as_backend(getattr(settings, "judgment_backend", "local")),
    )


# --- The posture in force for the current request --------------------------

_ACTIVE: contextvars.ContextVar[Posture | None] = contextvars.ContextVar(
    "agentfox_judgment_posture", default=None
)


def effective() -> Posture:
    """The posture in force here and now.

    A context variable rather than a process global because posture is per tenant and
    the gateway serves several in one process. Unset — a CLI run, a benchmark, a
    library embedding — means the deployment's own settings, unchanged.
    """
    active = _ACTIVE.get()
    return active if active is not None else from_settings()


@contextmanager
def use(posture: Posture | None) -> Iterator[None]:
    """Make `posture` the one in force for the duration of the block."""
    token = _ACTIVE.set(posture)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def activate(posture: Posture | None) -> contextvars.Token[Posture | None]:
    """Set the active posture without a block — for a request-scoped dependency.

    The caller owns the returned token and must reset it. Prefer :func:`use`; this
    exists because a FastAPI dependency's teardown is a separate frame from its setup.
    """
    return _ACTIVE.set(posture)


def deactivate(token: contextvars.Token[Posture | None]) -> None:
    _ACTIVE.reset(token)


# --- Storage ---------------------------------------------------------------


def load(session: Session) -> Posture:
    """This tenant's stored posture, clamped to the ceiling — or settings if unset.

    Clamped on read, not just on write: a deployment that has since revoked egress
    must not be reported as sending data because a row written before the revocation
    still says so.
    """
    row = _row(session)
    if row is None:
        return Ceiling.from_settings().clamp(from_settings())
    stored = Posture(
        tiers=frozenset(_as_tiers(row.tiers)),
        pii_egress=_as_pii(row.pii_egress),
        fail_closed=bool(row.fail_closed),
        backend=_as_backend(row.backend),
        version=int(row.version or 1),
    )
    return Ceiling.from_settings().clamp(stored)


def save(
    session: Session,
    posture: Posture,
    *,
    actor: str,
    reason: str,
    confirm_egress: bool = False,
) -> Posture:
    """Store a posture, refusing anything the deployment does not permit.

    ``confirm_egress`` is required for any change that *starts* sending data off this
    machine, or that loosens how personal data is handled on the way. It is not
    paternalism about a checkbox: these are the two changes in the product whose
    consequence is invisible from the screen that makes them — nothing breaks, no
    latency moves, and the first observable effect is a customer's data in a third
    party's logs. Everything else about this write is ordinary.

    Recorded through the operator log, so the chain carries who widened the posture,
    when, why, and what it was before.
    """
    from agentfox.core.models import JudgmentPosture
    from agentfox.platform.ledger.operator_log import record

    ceiling = Ceiling.from_settings()
    refusals = ceiling.refusals(posture)
    if refusals:
        raise PostureRefused(" ".join(refusals))

    row = _row(session)
    before = (
        Posture(
            tiers=frozenset(_as_tiers(row.tiers)),
            pii_egress=_as_pii(row.pii_egress),
            fail_closed=bool(row.fail_closed),
            backend=_as_backend(row.backend),
            version=int(row.version or 1),
        )
        if row is not None
        else Ceiling.from_settings().clamp(from_settings())
    )

    if _widens_egress(before, posture) and not confirm_egress:
        raise PostureRefused(
            "this change starts sending data off this machine, or loosens how "
            "personal data is handled on the way. Re-submit with confirm_egress=true "
            "to say that is intended. "
            f"Before: {before.to_json()}. After: {posture.to_json()}."
        )

    if row is None:
        row = JudgmentPosture()
        session.add(row)
        row.version = 1
    else:
        row.version = int(row.version or 1) + 1

    row.tiers = sorted(str(t) for t in posture.tiers)
    row.pii_egress = str(posture.pii_egress)
    row.fail_closed = bool(posture.fail_closed)
    row.backend = str(posture.backend)
    row.updated_by = actor
    session.flush()

    stored = replace(posture, version=row.version)
    record(
        session,
        "operator.judgment_posture.changed",
        actor=actor or "unknown",
        reason=reason,
        subject_type="judgment_posture",
        subject_id=row.id,
        before=before.to_json(),
        after=stored.to_json(),
        extra={"egress_widened": _widens_egress(before, posture)},
    )
    if stored.sends_anything:
        log.warning(
            "judgment posture now sends payloads off this machine: tiers=%s backend=%s "
            "pii_egress=%s (set by %s)",
            sorted(str(t) for t in stored.egress_tiers),
            stored.backend,
            stored.pii_egress,
            actor,
        )
    return stored


def _widens_egress(before: Posture, after: Posture) -> bool:
    """True when the change newly lets data leave, or lets more of it leave."""
    if after.egress_tiers - before.egress_tiers:
        return True
    if after.backend in _REMOTE_BACKENDS and before.backend not in _REMOTE_BACKENDS:
        return True
    return _PII_RANK[after.pii_egress] < _PII_RANK[before.pii_egress]


def _row(session: Session) -> Any:
    from sqlalchemy import select

    from agentfox.core.models import JudgmentPosture

    # One row per tenant, and the tenant filter is what selects it — so `limit(1)`
    # rather than a key lookup, which would need the org id spelled out here and
    # duplicate the filtering that `tenancy.py` already applies to every query.
    return session.scalars(select(JudgmentPosture).limit(1)).first()


# --- Coercion --------------------------------------------------------------


def _as_pii(value: object) -> PiiEgress:
    try:
        return PiiEgress(str(value).strip().lower())
    except ValueError:
        # The strict reading of an unreadable setting, not the permissive one.
        log.warning("unknown pii_egress %r; falling back to 'block'", value)
        return PiiEgress.BLOCK


def _as_backend(value: object) -> Backend:
    try:
        return Backend(str(value).strip().lower())
    except ValueError:
        log.warning("unknown judgment backend %r; falling back to 'local'", value)
        return Backend.LOCAL


def _as_tiers(values: object) -> set[Tier]:
    out: set[Tier] = set()
    for name in values or []:  # type: ignore[union-attr]
        try:
            out.add(Tier(str(name).strip().lower()))
        except ValueError:
            log.warning("ignoring unknown judgment tier %r", name)
    return out
