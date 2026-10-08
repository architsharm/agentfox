"""Protect an agent in one flow: protections and sensitivity, its own words and topics,
the message its users see, then a preview over its own recent traffic.

* ``GET  /api/agents/{slug}/protection``          — what protects it now
* ``POST /api/agents/{slug}/protection/preview``  — what a setup would have done; saves nothing
* ``POST /api/agents/{slug}/protection``          — save it

The protections are the agent's policy layer (`capabilities/protection`); the words
and topics are custom rules scoped to the agent, under keys this flow owns
(``<slug>-words``, ``<slug>-avoid``, ``<slug>-allowed``) so re-running the setup
edits them instead of piling up copies. Everything new starts watching.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, get_agent_or_404, require
from agentfox.capabilities import protection
from agentfox.capabilities.detection import all_detectors
from agentfox.capabilities.detection.custom import CustomRuleSpec
from agentfox.capabilities.detection.custom_store import (
    RuleSeed,
    delete_rule,
    get_rule,
    save_rules,
    spec_of,
)
from agentfox.capabilities.detection.detector_settings import enabled_for, set_enabled
from agentfox.core.models import User
from agentfox.platform.policy.simulate import simulate

router = APIRouter(prefix="/api/agents", tags=["protection"])

Level = Literal["off", "on", "low", "medium", "high"]


def _owned_keys(slug: str) -> dict[str, str]:
    """The custom-rule keys this flow owns for an agent, at most 63 characters."""
    base = slug.lower()[:50]
    return {"words": f"{base}-words", "avoid": f"{base}-avoid", "allowed": f"{base}-allowed"}


def _words_and_topics(session: Session, slug: str) -> dict[str, Any]:
    keys = _owned_keys(slug)
    out: dict[str, Any] = {"words": [], "avoid": "", "allowed": ""}
    if (row := get_rule(session, keys["words"])) is not None:
        out["words"] = spec_of(row).entries
    for field in ("avoid", "allowed"):
        if (row := get_rule(session, keys[field])) is not None:
            out[field] = spec_of(row).description
    return out


@router.get("/{slug}/protection")
def get_protection(
    slug: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    get_agent_or_404(session, slug)
    detectors = all_detectors()
    on = enabled_for(session)
    body = protection.state(session, slug).to_json()
    for p in body["protections"]:
        for field in ("needs", "better"):
            key = p[field]
            if key:
                p[f"{field}_installed"] = bool(detectors.get(key) and detectors[key].available())
                p[f"{field}_on"] = key in on
    return {**body, **_words_and_topics(session, slug)}


class SetupIn(BaseModel):
    protections: dict[str, Level] = Field(default_factory=dict)
    message: str = Field("", max_length=500)
    words: list[str] = Field(default_factory=list, max_length=500)
    avoid: str = Field("", max_length=2000)
    allowed: str = Field("", max_length=2000)


def _layer(slug: str, payload: SetupIn):
    try:
        return protection.build_layer(slug, payload.protections, payload.message.strip())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{slug}/protection/preview")
def preview_protection(
    slug: str, payload: SetupIn, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    """Replay this agent's last week against the protections, as if enforcing."""
    get_agent_or_404(session, slug)
    doc = _layer(slug, payload)
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=7)
    return simulate(session, doc, agent_slug=slug, since=since).to_json()


def _custom_specs(slug: str, payload: SetupIn) -> tuple[list[CustomRuleSpec], list[str]]:
    """Specs to save, and owned keys whose field was cleared (to delete)."""
    keys = _owned_keys(slug)
    save: list[CustomRuleSpec] = []
    clear: list[str] = []
    words = [w.strip() for w in payload.words if w.strip()]
    if words:
        save.append(
            CustomRuleSpec(
                key=keys["words"], name=f"{slug}: blocked words", entries=words, agents=[slug]
            )
        )
    else:
        clear.append(keys["words"])
    for field, polarity, name, surfaces in (
        ("avoid", "deny", "topics to avoid", ["input", "output"]),
        ("allowed", "allow", "allowed topics", ["input"]),
    ):
        text = getattr(payload, field).strip()
        if text:
            save.append(
                CustomRuleSpec(
                    key=keys[field],
                    name=f"{slug}: {name}",
                    kind="topic",
                    polarity=polarity,
                    description=text,
                    surfaces=surfaces,
                    agents=[slug],
                )
            )
        else:
            clear.append(keys[field])
    return save, clear


@router.post("/{slug}/protection")
def save_protection(
    slug: str,
    payload: SetupIn,
    session: Session = Depends(db),
    user: User = Depends(require("policy")),
) -> dict[str, Any]:
    get_agent_or_404(session, slug)
    _layer(slug, payload)  # validate before writing anything
    actor = user.email or user.id
    message = payload.message.strip()

    published = protection.save(session, slug, payload.protections, message, actor=actor)

    specs, clear = _custom_specs(slug, payload)
    custom = None
    if specs:
        seed = RuleSeed(effect="block", message=message)
        custom = save_rules(
            session, [(s, seed) for s in specs], actor=actor, reason=f"protection for {slug}"
        )[1]
    for key in clear:
        if get_rule(session, key) is not None:
            custom = delete_rule(session, key, actor=actor) or custom

    detectors = all_detectors()
    switched, not_installed = [], []
    for key in protection.needed_detectors(payload.protections):
        if detectors.get(key) and detectors[key].available():
            set_enabled(session, key, True, actor=actor, reason=f"needed to protect {slug}")
            switched.append(key)
        else:
            not_installed.append(key)

    return {
        "policy": {
            "key": protection.layer_key(slug),
            "version": published.version,
            "mode": published.mode,
            "simulation": published.simulation,
        },
        "custom_policy": {"version": custom.version, "mode": custom.mode} if custom else None,
        "detectors": switched,
        "not_installed": not_installed,
    }
