"""What `agentfox init` and the dashboard may send the onboarding API, validated.

Before this a structure was an untyped dict: a malformed one reached the registry and
failed there with a 500 (an agent without a name), or was silently mangled (a string
where a list belongs was split into characters). Every field has a size limit, and a
test's results are capped, so nothing a runner sends can grow a row without bound.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The longest project name: `Agent.project` is a String(120).
PROJECT_MAX = 120
#: Results one report may carry. A whole test is a few hundred attacks at most, and
#: the runner reports every second or so.
RESULTS_PER_REPORT = 500
_ID = 200
_TEXT = 2_000


class _Item(BaseModel):
    # Unknown fields are dropped rather than refused, so an older or newer `init`
    # still connects; only the fields the product reads are kept.
    model_config = ConfigDict(extra="ignore")


class Source(_Item):
    id: str = Field(max_length=_ID)
    label: str = Field(default="", max_length=_ID)
    detail: str | None = Field(default=None, max_length=_TEXT)


class MappedAgent(_Item):
    id: str = Field(max_length=_ID)
    name: str = Field(min_length=1, max_length=_ID)
    model: str | None = Field(default=None, max_length=_ID)
    models: list[str] | None = Field(default=None, max_length=50)
    sourceIds: list[str] = Field(default_factory=list, max_length=200)  # noqa: N815
    handsOffTo: list[str] = Field(default_factory=list, max_length=200)  # noqa: N815
    framework: str | None = Field(default=None, max_length=64)
    addedByUser: bool | None = None  # noqa: N815
    #: Where the attack test finds the live object: module, the name in it, and its
    #: kind (``object``, ``factory``, ``function``), as discovery reports them.
    module: str | None = Field(default=None, max_length=_ID)
    attr: str | None = Field(default=None, max_length=_ID)
    attrKind: str | None = Field(default=None, max_length=32)  # noqa: N815


class MappedTool(_Item):
    id: str | None = Field(default=None, max_length=_ID)
    name: str = Field(min_length=1, max_length=_ID)
    agentId: str = Field(max_length=_ID)  # noqa: N815
    risk: str | None = Field(default=None, max_length=32)
    whatItDoes: str = Field(default="", max_length=_TEXT)  # noqa: N815
    systemId: str | None = Field(default=None, max_length=_ID)  # noqa: N815
    args: list[str] | None = Field(default=None, max_length=100)
    addedByUser: bool | None = None  # noqa: N815


class System(_Item):
    id: str = Field(max_length=_ID)
    name: str = Field(min_length=1, max_length=_ID)
    kind: str = Field(default="", max_length=64)


class Structure(_Item):
    sources: list[Source] = Field(default_factory=list, max_length=200)
    agents: list[MappedAgent] = Field(default_factory=list, max_length=200)
    tools: list[MappedTool] = Field(default_factory=list, max_length=2_000)
    systems: list[System] = Field(default_factory=list, max_length=500)

    def as_dict(self) -> dict[str, Any]:
        out = self.model_dump(exclude_none=True)
        return {k: out.get(k, []) for k in ("sources", "agents", "tools", "systems")}


class Connect(BaseModel):
    structure: Structure
    #: The repository's name: the project its agents are grouped under.
    project: str | None = Field(default=None, min_length=1, max_length=PROJECT_MAX)


class Poll(BaseModel):
    #: The project this runner serves (newer `init`s say; older ones don't, and get
    #: the project they connected last).
    project: str | None = Field(default=None, min_length=1, max_length=PROJECT_MAX)
    #: What the runner can do: 2 checks an "after" test against the project's real
    #: policies (``/runner/runs/{id}/guard``). Older runners don't say, and are not
    #: handed an "after" test (they would simulate guardrails that aren't the project's).
    protocol: int | None = Field(default=None, ge=1, le=100)


class AttackOutcome(_Item):
    id: str = Field(max_length=_ID)
    type: str = Field(max_length=64)
    gotThrough: bool | None = None  # noqa: N815
    error: str | None = Field(default=None, max_length=_TEXT)
    sentence: str | None = Field(default=None, max_length=_TEXT)
    attack: str | None = Field(default=None, max_length=20_000)
    toolCall: str | None = Field(default=None, max_length=4_000)  # noqa: N815
    owasp: list[str] | None = Field(default=None, max_length=20)
    severity: float | None = None
    calls: list[Any] | None = Field(default=None, max_length=50)
    #: got_through | stopped | resisted | errored | not_run, or for a control
    #: allowed | over_blocked | errored.
    outcome: str | None = Field(default=None, max_length=32)
    agent: str | None = Field(default=None, max_length=_ID)
    #: The rule that stopped it: surface, rule, verdict, mode, reason, tool, watching.
    stoppedBy: dict[str, Any] | None = None  # noqa: N815
    control: bool | None = None
    reason: str | None = Field(default=None, max_length=_TEXT)

    @model_validator(mode="after")
    def _calls_fit(self) -> AttackOutcome:
        if self.calls is not None and len(json.dumps(self.calls, default=str)) > 20_000:
            raise ValueError("calls is too large")
        if self.stoppedBy is not None and len(json.dumps(self.stoppedBy, default=str)) > 4_000:
            raise ValueError("stoppedBy is too large")
        return self


class Results(BaseModel):
    results: list[AttackOutcome] = Field(default_factory=list, max_length=RESULTS_PER_REPORT)
    done: bool = False
    error: str | None = Field(default=None, max_length=_TEXT)


class GuardCheck(BaseModel):
    """One surface of one attack, for the project's policies to judge (an "after" test)."""

    #: The agent's registry slug (from the job's structure).
    agent: str = Field(min_length=1, max_length=_ID)
    #: input | tool_call | tool_result | output
    surface: str = Field(max_length=32)
    content: str = Field(default="", max_length=50_000)
    tool: str | None = Field(default=None, max_length=_ID)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _fits(self) -> GuardCheck:
        if len(json.dumps(self.arguments, default=str)) > 20_000:
            raise ValueError("arguments is too large")
        return self
