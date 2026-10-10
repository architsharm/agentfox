"""Every kind of finding the product raises: its title, default severity, meaning, owner.

A finding's ``type`` is a short slug (``shadow_agent``, ``containment``) that the
queue, the dashboard, webhooks and the compliance status rules all key on. Without a
registry each was a free string at its call site, the dashboard kept its own label
table, and a typo raised a finding nothing else recognised. This module is the one
list: `raise_finding` checks a type against it, ``GET /api/findings/types`` serves
it, and the dashboard's labels are generated from it.

Capability packs declare their own types in ``pack.yaml`` (``finding_types``); they
are added on first use. Code can register more with `register`.

``owner`` is the capability, platform package or pack that raises the type. The
default severity is what the type is usually raised at; the call site still decides.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger(__name__)

#: Set (to anything but ``0``/``false``) to make an unregistered type an error rather
#: than a warning. The test suite sets it; production never crashes over a slug.
STRICT_ENV = "AGENTFOX_STRICT_FINDING_TYPES"

SEVERITIES = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class FindingType:
    type: str
    title: str
    severity: str
    description: str
    owner: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _t(type_: str, title: str, severity: str, owner: str, description: str) -> FindingType:
    return FindingType(type_, title, severity, description, owner)


BUILTIN: tuple[FindingType, ...] = (
    # --- detection and the request path ------------------------------------------
    _t(
        "guardrail_detection",
        "Guardrail catch",
        "high",
        "detection",
        "A detector caught something in a request or response and it changed the "
        "outcome — see the masked excerpt below.",
    ),
    _t(
        "trajectory_drift",
        "Escalating conversation",
        "high",
        "detection",
        "The conversation as a whole is escalating towards something the single turns do not show.",
    ),
    _t(
        "budget_breach",
        "Detector over budget",
        "medium",
        "platform.ledger",
        "A detector was skipped or timed out against its latency budget, so this "
        "agent's calls ran with less coverage.",
    ),
    _t(
        "budget_exhausted",
        "Budget exhausted",
        "high",
        "runtime",
        "This agent has used up its configured cost or call budget.",
    ),
    _t(
        "agent_loop_stopped",
        "Loop stopped",
        "high",
        "runtime",
        "The proxy stopped a tool-calling run that kept repeating the same call.",
    ),
    _t(
        "boundary_breach",
        "Answered outside its boundary",
        "medium",
        "grounding",
        "The agent answered beyond the knowledge boundary it declared.",
    ),
    # --- containment --------------------------------------------------------------
    _t(
        "containment",
        "Contained action",
        "high",
        "containment",
        "A tool call was stopped or held by a permission, data-provenance or "
        "blast-radius rule — not by a content detector. The title says which, and "
        "whether it was enforced or only observed.",
    ),
    _t(
        "control_flow",
        "Injected step",
        "high",
        "containment",
        "A tool call that exists because of untrusted content the agent read, not the "
        "user's request, even with clean arguments.",
    ),
    _t(
        "missed_escalation",
        "Missed hand-off",
        "high",
        "containment",
        "A conversation should have gone to a human and didn't.",
    ),
    _t(
        "handoff_sla_breach",
        "Hand-off overdue",
        "high",
        "containment",
        "A human hand-off has gone unacknowledged past its deadline.",
    ),
    _t(
        "incomplete_handoff",
        "Incomplete hand-off",
        "medium",
        "containment",
        "Context the next step needed was missing when work was handed off.",
    ),
    _t(
        "false_resolution",
        "False resolution",
        "high",
        "containment",
        "Marked resolved without actually resolving the user's issue.",
    ),
    # --- grounding: what an answer said -------------------------------------------
    _t(
        "source_authority",
        "Untrusted source",
        "medium",
        "grounding",
        "Used a source below the trust tier this required.",
    ),
    _t(
        "fabricated_citation",
        "Fabricated citation",
        "high",
        "grounding",
        "Cited a source that doesn't say what it claims, or doesn't exist.",
    ),
    _t(
        "source_conflict",
        "Conflicting sources",
        "medium",
        "grounding",
        "Two sources disagreed and the conflict wasn't surfaced.",
    ),
    _t(
        "integrity_error",
        "Data integrity error",
        "medium",
        "grounding",
        "A numeric, temporal, or identity error was detected in the output.",
    ),
    _t(
        "entitlement_disclosure",
        "Disclosure risk",
        "critical",
        "grounding",
        "May have disclosed something the requester wasn't entitled to see.",
    ),
    _t(
        "aggregation_disclosure",
        "Disclosure risk",
        "high",
        "grounding",
        "Combined otherwise-safe facts into something the requester shouldn't see.",
    ),
    _t(
        "inference_disclosure",
        "Disclosure risk",
        "high",
        "grounding",
        "Let the requester infer something they weren't entitled to know.",
    ),
    _t(
        "binding_commitment",
        "Binding commitment",
        "high",
        "grounding",
        "The answer promised, decided or quoted something on the company's behalf that "
        "the agent was not authorised to.",
    ),
    _t(
        "register_breach",
        "Overconfident advice",
        "medium",
        "grounding",
        "Specific advice in a regulated domain, or an unhedged claim about the future, "
        "without the standing to give it.",
    ),
    _t(
        "ai_impersonation",
        "Claimed to be human",
        "high",
        "grounding",
        "The answer told the person it was a human.",
    ),
    _t(
        "ai_disclosure_missing",
        "AI not disclosed",
        "medium",
        "grounding",
        "The person was not told they were talking to an AI system.",
    ),
    _t(
        "adverse_action",
        "Unexplained adverse decision",
        "high",
        "grounding",
        "An adverse decision was communicated without the reasons the record or the law requires.",
    ),
    _t(
        "sycophancy",
        "Adopted a false premise",
        "medium",
        "grounding",
        "The answer went along with something the user asserted that the grounded "
        "record contradicts.",
    ),
    _t(
        "context_integrity",
        "Damaged context",
        "medium",
        "grounding",
        "What the agent read was corrupt, badly chunked, drifting from its retrieval "
        "baseline, or a memory about someone else.",
    ),
    _t(
        "over_refusal",
        "Over-refusal",
        "medium",
        "grounding",
        "The agent is refusing requests it should be able to answer.",
    ),
    # --- registry, identity, MCP ------------------------------------------------------
    _t(
        "shadow_agent",
        "Unregistered agent",
        "high",
        "platform.registry",
        "This agent is sending traffic but was never registered.",
    ),
    _t(
        "unowned_agent",
        "No owner",
        "medium",
        "platform.registry",
        "No one is accountable for this agent's decisions.",
    ),
    _t(
        "registry_drift",
        "Registry drift",
        "medium",
        "platform.registry",
        "What this agent actually calls no longer matches what it declared.",
    ),
    _t(
        "delegation_cycle",
        "Delegation loop",
        "high",
        "platform.registry",
        "Agent-to-agent delegation loops back on itself.",
    ),
    _t(
        "delegation_depth",
        "Delegation too deep",
        "medium",
        "platform.registry",
        "Agent-to-agent delegation is nested deeper than allowed.",
    ),
    _t(
        "agent_stopped",
        "Agent stopped",
        "high",
        "platform.registry",
        "Traffic was halted by a kill switch or quarantine.",
    ),
    _t(
        "schema_drift",
        "Schema drift",
        "high",
        "platform.registry",
        "A data source's structure changed unexpectedly.",
    ),
    _t(
        "tool_poisoning",
        "Tool poisoning",
        "critical",
        "platform.registry",
        "A tool's behavior changed in a way that looks like tampering.",
    ),
    _t(
        "unpinned_server",
        "Unpinned MCP server",
        "medium",
        "platform.registry",
        "Not pinned to a known-good version.",
    ),
    _t(
        "undeclared_mcp_tool",
        "Undeclared tool use",
        "high",
        "frameworks.mcp",
        "The agent called a tool it never declared using.",
    ),
    _t(
        "mcp_schema_drift",
        "Tool contract changed",
        "high",
        "frameworks.mcp",
        "A tool's schema changed after approval — possible tampering.",
    ),
    _t(
        "mcp_tool_added_under_wildcard",
        "New tool under a wildcard grant",
        "medium",
        "frameworks.mcp",
        "An MCP server added a tool that an existing wildcard grant lets the agent "
        "call without anyone approving it.",
    ),
    _t(
        "orphaned_identity",
        "Orphaned identity",
        "medium",
        "platform.identity",
        "An agent identity with no active agent behind it.",
    ),
    _t(
        "stale_identity",
        "Stale identity",
        "medium",
        "platform.identity",
        "An agent identity nobody has used for the staleness window still holds its grants.",
    ),
    _t(
        "over_privileged",
        "Over-privileged identity",
        "high",
        "platform.identity",
        "An agent identity holds an unrestricted '*' tool grant.",
    ),
    # --- skills scanned from a repository -----------------------------------------
    _t(
        "skill_poisoning",
        "Poisoned skill",
        "critical",
        "discovery",
        "A skill file's description or body reads like instructions to the model.",
    ),
    _t(
        "skill_dangerous_command",
        "Dangerous command in a skill",
        "high",
        "discovery",
        "A skill tells the agent to run a destructive or exfiltrating command.",
    ),
    _t(
        "skill_bundled_code",
        "Skill bundles code",
        "high",
        "discovery",
        "A skill ships executable code alongside its instructions.",
    ),
    _t(
        "skill_malformed_frontmatter",
        "Malformed skill",
        "medium",
        "discovery",
        "A skill's front matter does not parse, so its declared limits do not apply.",
    ),
    _t(
        "skill_overbroad_tools",
        "Skill allows too much",
        "high",
        "discovery",
        "A skill grants itself more tools than its job needs.",
    ),
    # --- evaluation and red team ------------------------------------------------------
    _t(
        "redteam",
        "Security test",
        "high",
        "evaluation",
        "Simulated attacks got through without being blocked.",
    ),
    _t(
        "redteam_over_block",
        "Over-blocking",
        "medium",
        "evaluation",
        "The agent refused legitimate requests from the test's control group — a "
        "guardrail that blocks real work gets switched off.",
    ),
    _t(
        "redteam_mutation_class",
        "Evasion that works",
        "high",
        "evaluation",
        "A class of rewording got blocked attacks through in an adaptive campaign.",
    ),
    _t(
        "redteam_posture_regression",
        "Weaker than last time",
        "high",
        "evaluation",
        "This deployment let through attacks the previous adaptive campaign blocked.",
    ),
    _t(
        "live_probe_escape",
        "Live probe got through",
        "high",
        "evaluation",
        "A probe sent to the deployed agent's endpoint was not stopped.",
    ),
    _t(
        "drift",
        "Model drift",
        "medium",
        "evaluation",
        "This model's outputs have measurably changed from its baseline.",
    ),
    _t(
        "new_tool_path",
        "New tool path",
        "low",
        "evaluation",
        "The agent called its tools in an order never seen before, and no test expects it.",
    ),
    # --- continuous monitoring ---------------------------------------------------------
    _t(
        "monitor_lethal_trifecta",
        "Lethal trifecta",
        "high",
        "monitoring",
        "A monitored source gives one agent private data, untrusted content and a way "
        "to send data out.",
    ),
    _t(
        "monitor_ungoverned_model_call",
        "Ungoverned model call",
        "medium",
        "monitoring",
        "A monitored repository calls a model that AgentFox does not govern.",
    ),
    _t(
        "monitor_governance_removed",
        "Governance removed",
        "high",
        "monitoring",
        "Code that governed a model call was removed from a monitored repository.",
    ),
    _t(
        "monitor_new_tool",
        "New tool",
        "low",
        "monitoring",
        "A monitored source exposes a tool it did not have at the last run.",
    ),
    _t(
        "monitor_new_mcp_server",
        "New MCP server",
        "medium",
        "monitoring",
        "A monitored repository configures an MCP server it did not have at the last run.",
    ),
    _t(
        "monitor_api_destructive_endpoint",
        "New destructive endpoint",
        "high",
        "monitoring",
        "A monitored API spec added an endpoint that deletes or overwrites.",
    ),
    _t(
        "monitor_api_new_endpoint",
        "New endpoint",
        "low",
        "monitoring",
        "A monitored API spec added an endpoint.",
    ),
    _t(
        "monitor_failing",
        "Monitor failing",
        "medium",
        "monitoring",
        "A monitored source could not be checked.",
    ),
)

_REGISTRY: dict[str, FindingType] = {t.type: t for t in BUILTIN}
_packs_loaded = False
_warned: set[str] = set()


def register(finding_type: FindingType) -> FindingType:
    """Add a type. A type registered twice keeps its first definition."""
    if finding_type.severity not in SEVERITIES:
        raise ValueError(
            f"finding type {finding_type.type!r}: severity must be one of {SEVERITIES}"
        )
    return _REGISTRY.setdefault(finding_type.type, finding_type)


def _load_pack_types() -> None:
    global _packs_loaded
    if _packs_loaded:
        return
    _packs_loaded = True
    try:
        from agentfox.platform.packs import load_packs

        for pack in load_packs():
            for spec in pack.manifest.finding_types:
                register(
                    FindingType(
                        type=spec.type,
                        title=spec.title,
                        severity=spec.severity,
                        description=spec.description,
                        owner=f"pack:{pack.id}",
                    )
                )
    except Exception:  # pragma: no cover - a broken pack must not break findings
        log.warning("finding types from capability packs could not be loaded", exc_info=True)


def all_types() -> list[FindingType]:
    """Every registered type, built-in first, in registration order."""
    _load_pack_types()
    return list(_REGISTRY.values())


def get(type_: str) -> FindingType | None:
    _load_pack_types()
    return _REGISTRY.get(type_)


def is_registered(type_: str) -> bool:
    return get(type_) is not None


def strict() -> bool:
    return os.environ.get(STRICT_ENV, "").lower() not in ("", "0", "false", "no")


class UnregisteredFindingType(ValueError):
    """A finding was raised with a type nobody registered (strict mode only)."""


def check(type_: str) -> None:
    """Warn (once per type) about an unregistered type, or raise in strict mode."""
    if is_registered(type_):
        return
    if strict():
        raise UnregisteredFindingType(
            f"finding type {type_!r} is not registered; add it to "
            "platform/ledger/finding_types.py or the pack's finding_types"
        )
    if type_ not in _warned:
        _warned.add(type_)
        log.warning("finding type %r is not registered", type_)


def reset_pack_types() -> None:
    """Forget pack-declared types so the next lookup reads the packs again (tests)."""
    global _packs_loaded
    for key in [k for k, t in _REGISTRY.items() if t.owner.startswith("pack:")]:
        del _REGISTRY[key]
    _packs_loaded = False


__all__ = [
    "BUILTIN",
    "SEVERITIES",
    "STRICT_ENV",
    "FindingType",
    "UnregisteredFindingType",
    "all_types",
    "check",
    "get",
    "is_registered",
    "register",
    "reset_pack_types",
    "strict",
]
