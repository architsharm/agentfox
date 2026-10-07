"""The ``pack.yaml`` schema: what a capability pack says about itself.

A pack is a directory of data (policies, controls, ladders, probes, cases, fixtures)
plus optional checks, described by a ``pack.yaml`` validated by `PackManifest`. The
JSON Schema for editors is `PackManifest.model_json_schema()` (`agentfox policy packs
validate --schema` prints it).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Lowest first. A deployment loads packs at or above its `pack_maturity` setting:
#: ``stable`` (the default) loads only stable packs, ``incubating`` adds incubating
#: ones, ``sandbox`` loads everything.
MATURITIES = ("stable", "incubating", "sandbox")

#: The directories a pack may have, beside ``pack.yaml`` and ``README.md``.
LAYOUT = ("policies", "controls", "ladders", "probes", "checks", "cases", "fixtures")

_ID = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)*$")
_VERSION = re.compile(r"^\d+\.\d+(\.\d+)?([-+][0-9A-Za-z.-]+)?$")
_SPEC = re.compile(r"^\s*(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+){0,2})\s*$")


class FindingTypeSpec(BaseModel):
    """A finding type the pack's checks raise (registered with the ledger)."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    description: str = ""


class Fallback(BaseModel):
    """When this pack's policies protect a deployment that has bound nothing.

    ``risk_tiers`` are the agent risk tiers it applies to (``"*"`` for every tier);
    ``order`` sorts the packs that apply, lowest first. Only built-in packs are
    consulted, and the policies are always forced to observe.
    """

    model_config = ConfigDict(extra="forbid")

    risk_tiers: list[str]
    order: int = 0


class Compliance(BaseModel):
    """What the pack evidences: control keys, and framework references by framework."""

    model_config = ConfigDict(extra="forbid")

    controls: list[str] = Field(default_factory=list)
    frameworks: dict[str, list[str]] = Field(default_factory=dict)


class PackManifest(BaseModel):
    """``pack.yaml``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Slash-separated, lower case: `payments/refunds`.")
    version: str
    maturity: Literal["stable", "incubating", "sandbox"] = "incubating"
    requires_core: str = Field(
        default="",
        description="Comma-separated version constraints on agentfox, e.g. `>=0.3`.",
    )
    title: str = ""
    description: str = ""
    owners: list[str] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    compliance: Compliance = Field(default_factory=Compliance)
    requires_detectors: list[str] = Field(default_factory=list)
    #: Words the pack teaches the product. Known keys: ``tool_hints`` and ``roles``
    #: (the policy compiler), ``condition_values`` (values a policy condition may
    #: take, for lint), ``annex_iii_cues`` and ``prohibited_cues`` (EU AI Act risk
    #: classification). Unknown keys are kept for checks to read.
    vocabulary: dict[str, Any] = Field(default_factory=dict)
    fallback: Fallback | None = None
    finding_types: list[FindingTypeSpec] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError(
                "must be lower-case words joined by '-', segments separated by '/' "
                "(e.g. payments/refunds)"
            )
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not _VERSION.match(str(value)):
            raise ValueError("must be a version such as 1.0 or 0.2.1")
        return str(value)

    @field_validator("requires_core")
    @classmethod
    def _requires_core(cls, value: str) -> str:
        for part in filter(None, (p.strip() for p in value.split(","))):
            if not _SPEC.match(part):
                raise ValueError(f"{part!r} is not a constraint such as >=0.3")
        return value


def _version_tuple(version: str) -> tuple[int, ...]:
    numbers = re.match(r"^\d+(?:\.\d+)*", version)
    parts = [int(p) for p in (numbers.group(0) if numbers else "0").split(".")]
    return tuple(parts + [0] * (3 - len(parts)))[:3]


def core_satisfies(requires_core: str, version: str) -> bool:
    """Does agentfox ``version`` meet every constraint in ``requires_core``?"""
    have = _version_tuple(version)
    for part in filter(None, (p.strip() for p in requires_core.split(","))):
        match = _SPEC.match(part)
        if match is None:
            return False
        op, want = match.group(1), _version_tuple(match.group(2))
        ok = {
            ">=": have >= want,
            "<=": have <= want,
            "==": have == want,
            "!=": have != want,
            ">": have > want,
            "<": have < want,
        }[op]
        if not ok:
            return False
    return True


__all__ = [
    "LAYOUT",
    "MATURITIES",
    "Compliance",
    "Fallback",
    "FindingTypeSpec",
    "PackManifest",
    "core_satisfies",
]
