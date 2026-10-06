"""The judgment posture surface — read it, and change it, from the product.

Everything the judgment router does can be configured by environment variable. That
is the right home for *whether this deployment may talk to a third party at all*: it
is set by whoever runs the process and accepts the risk, and no request should be
able to reach it. It is the wrong home for *whether we want remote judgment on
today*, which is a governance decision somebody makes repeatedly and which an auditor
later asks the history of. An environment variable has no author, no reason and no
history, and changing one needs a deploy — so in practice the answer to "who turned
this on in March" would be nobody.

So there are two layers, and the rule between them is enforced in
:mod:`agentfox.capabilities.judgment.posture`: **posture may only narrow what the deployment
permits.** This module is the HTTP face of that rule. Three things follow from it, and
they are the reason this is a route module rather than three fields on an existing one:

*The refusal is explicit.* Enabling a remote tier on a deployment with egress off
returns 409 with the reason, rather than storing a preference that does nothing. A
settings page showing JEV as enabled while nothing is sent to JEV has answered a
compliance question wrongly, in a screenshot somebody will attach to an attestation.

*Widening egress needs saying so twice.* `confirm_egress` is required for any change
that starts sending payloads off the machine or loosens how personal data is handled
on the way. These are the only two changes in the product whose consequence is
invisible from the screen that makes them: nothing breaks, no latency moves, and the
first observable effect is a customer's data in somebody else's logs.

*It is not a developer's call.* The write family is `judgment_posture`, which is
owner/admin/security — the same roster that may silence a detector, for the same
reason.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.capabilities.judgment import posture as _posture
from agentfox.capabilities.judgment.capability import (
    EGRESS_TIERS,
    EVIDENCE,
    ROUTING,
    CapabilityRouter,
    Combine,
    DecisionKind,
    Tier,
)
from agentfox.capabilities.judgment.egress import Backend, PiiEgress
from agentfox.core.models import User

router = APIRouter(prefix="/api/judgment", tags=["judgment"])


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _tier_catalogue(ceiling: _posture.Ceiling, active: _posture.Posture) -> list[dict[str, Any]]:
    """Every tier, whether it may be chosen here, and what it costs if it is.

    The UI needs all three — a checkbox the operator cannot tick is only honest if it
    says why — so they are computed once, here, rather than reconstructed in TypeScript
    from a flag and a guess.
    """
    out: list[dict[str, Any]] = []
    for tier in Tier:
        sends = tier in EGRESS_TIERS
        blocked = not ceiling.permits_tier(tier)
        out.append(
            {
                "tier": str(tier),
                "enabled": tier in active.tiers,
                "sends_data": sends,
                # DETERMINISTIC is not a choice: no key, no weights, no network, and
                # removing it leaves some kinds with nobody to decide them.
                "selectable": tier is not Tier.DETERMINISTIC and not blocked,
                "blocked_reason": (
                    "this deployment has egress switched off (AGENTFOX_ALLOW_EGRESS); "
                    "that is set by whoever runs the process, not from here"
                    if blocked
                    else (
                        "always on — it needs no key, no weights and no network"
                        if tier is Tier.DETERMINISTIC
                        else ""
                    )
                ),
            }
        )
    return out


def _kinds(router_: CapabilityRouter) -> dict[str, Any]:
    """Per decision kind: who would decide it under this posture, and who was refused.

    Rendered from the routing table rather than restated, so the page cannot drift
    from the policy it is describing.
    """
    out: dict[str, Any] = {}
    for kind in DecisionKind:
        plan = router_.plan(kind)
        rule = ROUTING[kind]
        out[kind.value] = {
            "combine": plan.combine.value,
            "deciders": [t.value for t in plan.deciders],
            "refused": {
                t.value: plan.why(t) for t in plan.excluded_tiers() if t is not Tier.DETERMINISTIC
            },
            # Only under CASCADE: the band is what decides whether an answer settles
            # the question or is passed to the next tier, and it means nothing for a
            # rule that never cascades. Reporting the dataclass default there would
            # invite someone to read significance into it.
            "band": (list(rule.band) if plan.combine is Combine.CASCADE and rule.band else None),
            # The measured basis for the routing above, so the page can answer
            # "why is code preferred here" with a number rather than an assertion.
            "measured": {
                t.value: {
                    "accuracy": m.accuracy,
                    "n": m.n,
                    "corpus": m.corpus,
                    "note": m.note,
                }
                for (k, t), m in EVIDENCE.items()
                if k is kind
            },
        }
    return out


def view(session: Session) -> dict[str, Any]:
    """The whole posture surface in one payload.

    One request rather than four, because every part of this screen is only meaningful
    next to the others: "JEV is off" and "this deployment forbids egress" are the same
    fact told twice, and a UI that fetched them separately would render the second one
    late and contradict itself for a frame.
    """
    active = _posture.load(session)
    ceiling = _posture.Ceiling.from_settings()
    return {
        "posture": active.to_json(),
        "ceiling": {
            "allow_egress": ceiling.allow_egress,
            "pii_egress": str(ceiling.pii_egress),
            "fail_closed_required": ceiling.fail_closed,
            "explains": (
                "Set by the process environment, not from this page. Posture may "
                "narrow these and may never widen them."
            ),
        },
        "tiers": _tier_catalogue(ceiling, active),
        "pii_egress_options": [
            {
                "value": str(PiiEgress.BLOCK),
                "label": "Block",
                "detail": (
                    "Nothing containing detected personal data leaves, redacted or "
                    "not. The only setting under which a remote tier cannot disclose "
                    "a subject's data."
                ),
                "selectable": True,
            },
            {
                "value": str(PiiEgress.REDACT),
                "label": "Redact",
                "detail": (
                    "Mask what the local detector finds, send the remainder. Measured "
                    "cost about one point of the recall gain remote judgment exists "
                    "for; measured residual, the ~82% of personal data the local "
                    "detector does not find still leaves."
                ),
                "selectable": ceiling.permits_pii(PiiEgress.REDACT),
            },
            {
                "value": str(PiiEgress.ALLOW),
                "label": "Allow",
                "detail": "Send as-is. A deliberate downgrade, logged at warning.",
                "selectable": ceiling.permits_pii(PiiEgress.ALLOW),
            },
        ],
        "backends": [
            {"value": str(b), "selectable": b is Backend.LOCAL or ceiling.allow_egress}
            for b in Backend
        ],
        "sends_anything": active.sends_anything,
        "kinds": _kinds(CapabilityRouter(active.tiers, ceiling.allow_egress)),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/posture")
def read_posture(
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """What is in force, what may be changed, and what the deployment forbids.

    Readable by every role including `auditor`: the posture is the answer to "what
    left the building", and an auditor who cannot read it cannot audit anything else
    either.
    """
    return view(session)


class PostureRequest(BaseModel):
    tiers: list[str] = Field(
        default_factory=list,
        description="Tier names to enable. 'deterministic' is implicit and always on.",
    )
    pii_egress: str = Field("redact", description="block | redact | allow")
    fail_closed: bool = True
    backend: str = Field("local", description="local | remote | auto")
    reason: str = Field(
        "",
        description="Why this change is being made. Required — it is the field an "
        "investigation actually reads.",
    )
    confirm_egress: bool = Field(
        False,
        description="Required when the change starts sending payloads off this "
        "machine, or loosens how personal data is handled on the way.",
    )


@router.put("/posture")
def write_posture(
    payload: PostureRequest,
    session: Session = Depends(db),
    user: User = Depends(require("judgment_posture")),
) -> dict[str, Any]:
    """Replace the posture, refusing anything the deployment does not permit.

    A whole-document PUT rather than a PATCH of individual fields, deliberately: the
    dangerous changes here are *combinations* — a remote tier plus `pii_egress=allow`
    is a different decision from either alone — and a field-at-a-time API makes each
    half look innocuous and never shows anyone the pair.

    409 rather than 400 for a ceiling breach: the request is well-formed and the
    caller is permitted: it conflicts with the state of the deployment, and the
    distinction is what tells an admin to call whoever runs the process rather than
    retype the form.
    """
    if not (payload.reason or "").strip():
        raise HTTPException(
            422,
            "a posture change needs a stated reason; it is the one field an "
            "investigation actually reads",
        )
    try:
        wanted = _posture.Posture(
            tiers=frozenset(_coerce_tiers(payload.tiers)),
            pii_egress=PiiEgress(payload.pii_egress.strip().lower()),
            fail_closed=bool(payload.fail_closed),
            backend=Backend(payload.backend.strip().lower()),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        _posture.save(
            session,
            wanted,
            actor=user.email,
            reason=payload.reason.strip(),
            confirm_egress=payload.confirm_egress,
        )
    except _posture.PostureRefused as exc:
        raise HTTPException(409, str(exc)) from exc

    # Re-read rather than echo: what the caller gets back is what the next request
    # will act on, clamp included, which is not always what they sent.
    return view(session)


def _coerce_tiers(names: list[str]) -> set[Tier]:
    out: set[Tier] = set()
    for name in names:
        try:
            out.add(Tier(str(name).strip().lower()))
        except ValueError as exc:
            known = ", ".join(sorted(str(t) for t in Tier))
            raise ValueError(f"unknown tier '{name}'; known tiers are {known}") from exc
    return out
