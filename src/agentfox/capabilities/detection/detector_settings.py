"""A workspace switching individual detectors on or off.

`Settings.enabled_detectors` is the deployment's choice and stays the default. A
`DetectorSetting` row overrides it for one tenant — so a customer can turn on a
model-backed detector they installed, or switch a noisy one off, from the
dashboard instead of an environment variable and a restart.

Switching a detector off silences it for the whole workspace, which makes it a
privileged operator action recorded like a suppression (`operator_log.PRIVILEGED`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import DetectorSetting
from agentfox.platform.ledger import operator_log

#: Never switchable off per workspace: the always-on safety net, and the detector
#: that carries the workspace's own rules (its rules switch on and off instead).
ALWAYS_ON = frozenset({"injection.heuristic", "secrets.native", "custom.lists"})


def overrides(session: Session) -> dict[str, bool]:
    return {row.key: row.enabled for row in session.scalars(select(DetectorSetting))}


#: Runs wherever any detector runs, even if a deployment's list predates it: it only
#: matches rules the workspace wrote, so writing one is the opt-in.
WORKSPACE_RULES = "custom.lists"


def enabled_for(session: Session) -> frozenset[str]:
    """The detectors this workspace runs: the deployment's list, plus its overrides.

    `ALWAYS_ON` limits what a workspace may switch off; it does not add to the
    deployment's list. A deployment that runs no detectors at all (a bypass, a
    benchmark) gets none.
    """
    deployment = get_settings().enabled_detectors
    if not deployment:
        return frozenset()
    enabled = set(deployment) | {WORKSPACE_RULES}
    # Registering a model is the opt-in, like writing a rule; with none, the detector
    # is not selected, so its network budget is never granted for nothing.
    from agentfox.capabilities.detection.custom_models import DETECTOR_KEY, any_enabled

    if any_enabled(session):
        enabled.add(DETECTOR_KEY)
    for key, on in overrides(session).items():
        if on:
            enabled.add(key)
        elif key not in ALWAYS_ON:
            enabled.discard(key)
    return frozenset(enabled)


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
