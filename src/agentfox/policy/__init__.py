"""Pillars 2/3/6 — the policy layer.

One authored artefact drives both runtime enforcement and compliance reporting.
Two interchangeable engines implement it: a deterministic native evaluator
(the default, and the offline path) and OPA/Rego (the scale and expressiveness
upgrade). They are cross-verified in the test suite, which is what keeps the
"swappable" claim honest.
"""

from __future__ import annotations

from agentfox.policy.canary import (
    CanaryError,
    active_canary,
    canary_health,
    canary_rollout,
    pick_version_id,
    rollback_canary,
    start_canary,
)
from agentfox.policy.engine import NativePolicyEngine, PolicyEngine, combine
from agentfox.policy.hierarchy import (
    LEVELS,
    MODES,
    EffectivePolicy,
    LintFinding,
    PolicyLayer,
    ResolvedRule,
    lint_documents,
    lint_policy,
    lint_summary,
    resolve_effective,
)
from agentfox.policy.model import (
    Condition,
    DetectionCondition,
    Effect,
    FiredRule,
    PolicyDecision,
    PolicyDocument,
    PolicyInput,
    Rule,
)
from agentfox.policy.opa import OpaPolicyEngine, compile_to_rego
from agentfox.policy.simulate import (
    SimulationDiff,
    record_simulation,
    rules_fingerprint,
    simulate,
    simulation_for,
)
from agentfox.policy.store import (
    PROJECT_POLICY_DIR,
    PolicyPackError,
    UnloadablePolicyVersion,
    active_layers,
    active_policies,
    agent_team,
    current_binding,
    effective_for,
    get_engine,
    history,
    lint_all,
    load_available,
    load_from_dir,
    load_version_document,
    pack_sources,
    policies_in_force,
    project_policy_dir,
    save_policy,
    set_mode,
)

__all__ = [
    "LEVELS",
    "MODES",
    "CanaryError",
    "EffectivePolicy",
    "LintFinding",
    "PolicyLayer",
    "ResolvedRule",
    "Condition",
    "DetectionCondition",
    "Effect",
    "FiredRule",
    "NativePolicyEngine",
    "OpaPolicyEngine",
    "PolicyDecision",
    "PolicyDocument",
    "PolicyEngine",
    "PolicyInput",
    "Rule",
    "SimulationDiff",
    "UnloadablePolicyVersion",
    "active_canary",
    "active_layers",
    "active_policies",
    "agent_team",
    "current_binding",
    "policies_in_force",
    "canary_health",
    "canary_rollout",
    "effective_for",
    "combine",
    "compile_to_rego",
    "get_engine",
    "history",
    "lint_all",
    "load_version_document",
    "lint_documents",
    "lint_policy",
    "lint_summary",
    "PROJECT_POLICY_DIR",
    "PolicyPackError",
    "load_available",
    "load_from_dir",
    "pack_sources",
    "project_policy_dir",
    "pick_version_id",
    "record_simulation",
    "rules_fingerprint",
    "simulation_for",
    "resolve_effective",
    "rollback_canary",
    "save_policy",
    "set_mode",
    "simulate",
    "start_canary",
]
