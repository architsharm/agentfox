"""A workspace switching individual detectors on or off.

`Settings.enabled_detectors` is the deployment's choice and stays the default. A
`DetectorSetting` row overrides it for one tenant — so a customer can turn on a
model-backed detector they installed, or switch a noisy one off, from the
dashboard instead of an environment variable and a restart.

A project can change the workspace's choice for itself (`AgentDetectorSetting`), in
either direction: switch on a detector only it needs, or switch off one that is
noise for it. No row means it runs what the workspace runs, so a change for the
workspace reaches every project that has not changed that detector.

Switching a detector off silences it for the whole workspace, or for one project,
which makes both privileged operator actions recorded like a suppression
(`operator_log.PRIVILEGED`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import AgentDetectorSetting, DetectorSetting
from agentfox.platform.ledger import operator_log

#: Never switchable off per workspace: the always-on safety net, and the detector
#: that carries the workspace's own rules (its rules switch on and off instead).
ALWAYS_ON = frozenset(
    {"injection.heuristic", "secrets.native", "custom.lists", "custom.validators"}
)


def overrides(session: Session) -> dict[str, bool]:
    return {row.key: row.enabled for row in session.scalars(select(DetectorSetting))}


#: Runs wherever any detector runs, even if a deployment's list predates it: it only
#: matches rules the workspace wrote, so writing one is the opt-in.
WORKSPACE_RULES = "custom.lists"
#: The same for rules that run a validator with the workspace's settings.
WORKSPACE_VALIDATORS = "custom.validators"


def agent_overrides(session: Session, agent: str) -> dict[str, bool]:
    """What one project changed, by detector key."""
    return {
        row.key: row.enabled
        for row in session.scalars(
            select(AgentDetectorSetting).where(AgentDetectorSetting.agent == agent)
        )
    }


def enabled_for(session: Session, agent: str | None = None) -> frozenset[str]:
    """The detectors this workspace runs (or one project in it): the deployment's
    list, plus the workspace's overrides, plus the project's.

    `ALWAYS_ON` limits what a workspace may switch off; it does not add to the
    deployment's list. A deployment that runs no detectors at all (a bypass, a
    benchmark) gets none.
    """
    deployment = get_settings().enabled_detectors
    if not deployment:
        return frozenset()
    enabled = set(deployment) | {WORKSPACE_RULES, WORKSPACE_VALIDATORS}
    # Registering a model is the opt-in, like writing a rule; with none, the detector
    # is not selected, so its network budget is never granted for nothing.
    from agentfox.capabilities.detection.custom_models import DETECTOR_KEY, any_enabled

    if any_enabled(session):
        enabled.add(DETECTOR_KEY)
    layers = [overrides(session)]
    if agent:
        layers.append(agent_overrides(session, agent))
    for layer in layers:
        for key, on in layer.items():
            if on:
                enabled.add(key)
            elif key not in ALWAYS_ON:
                enabled.discard(key)
    return frozenset(enabled)


def enabled_anywhere(session: Session) -> frozenset[str]:
    """Every detector some workspace in this deployment may run: the deployment's
    list, plus any detector a workspace switched on. Startup warm-up reads this, so
    it loads a model only when something can actually call it.

    A deployment that runs no detectors at all gets none, as in `enabled_for`.
    """
    from agentfox.core.tenancy import system_scope

    deployment = get_settings().enabled_detectors
    if not deployment:
        return frozenset()
    with system_scope("warming the detectors any workspace switched on", routine=True):
        switched_on = set(
            session.scalars(select(DetectorSetting.key).where(DetectorSetting.enabled.is_(True)))
        ) | set(
            session.scalars(
                select(AgentDetectorSetting.key).where(AgentDetectorSetting.enabled.is_(True))
            )
        )
    return frozenset(deployment) | switched_on


def set_enabled(
    session: Session, key: str, enabled: bool, *, actor: str, reason: str
) -> DetectorSetting:
    if not enabled and key in ALWAYS_ON:
        raise ValueError(f"'{key}' cannot be switched off")
    row = session.scalar(select(DetectorSetting).where(DetectorSetting.key == key))
    before = row.enabled if row else key in get_settings().enabled_detectors
    if row is None:
        row = DetectorSetting(key=key)
        session.add(row)
    row.enabled = enabled
    row.updated_by = actor
    session.flush()
    operator_log.record(
        session,
        "operator.detector.toggled",
        actor=actor,
        reason=reason or f"detector '{key}' {'on' if enabled else 'off'}",
        subject_type="detector",
        subject_id=key,
        before={"enabled": before},
        after={"enabled": enabled},
    )
    return row


def set_enabled_for_agent(
    session: Session, agent: str, key: str, enabled: bool | None, *, actor: str, reason: str
) -> AgentDetectorSetting | None:
    """Switch a detector on or off for one project; ``None`` goes back to the workspace's."""
    if enabled is False and key in ALWAYS_ON:
        raise ValueError(f"'{key}' cannot be switched off")
    row = session.scalar(
        select(AgentDetectorSetting).where(
            AgentDetectorSetting.agent == agent, AgentDetectorSetting.key == key
        )
    )
    before = row.enabled if row else None
    if enabled is None:
        if row is not None:
            session.delete(row)
        row = None
    else:
        if row is None:
            row = AgentDetectorSetting(agent=agent, key=key)
            session.add(row)
        row.enabled = enabled
        row.updated_by = actor
    session.flush()
    word = {True: "on", False: "off", None: "back to the workspace setting"}[enabled]
    operator_log.record(
        session,
        "operator.agent_detector.toggled",
        actor=actor,
        reason=reason or f"detector '{key}' {word} for agent '{agent}'",
        subject_type="agent",
        subject_id=agent,
        before={"detector": key, "enabled": before},
        after={"detector": key, "enabled": enabled},
    )
    return row
