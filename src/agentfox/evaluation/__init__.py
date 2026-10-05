"""Pillar 4 — Evaluation & Reliability Assurance.

The widest solved-vs-unsolved gap in the stack, and the pillar that separates this
product from a pure-security tool: we govern whether the agent *worked*, not only
whether it was safe (principle X-5).
"""

from agentfox.evaluation import adapters, adaptive, drift, gating, redteam, runner, scorers, silent_failure
from agentfox.evaluation.adapters import PromptfooRunner, get_runner
from agentfox.evaluation.adaptive import (
    OPERATORS,
    SCOPE_STATEMENT,
    deployment_profile,
    generate_deployment_probes,
    mutation_classes,
)
from agentfox.evaluation.drift import DriftReport, evaluate_slos, ks_statistic, psi, set_slo
from agentfox.evaluation.drift import compute as compute_drift
from agentfox.evaluation.gating import GateResult, Regression, gate, set_baseline, to_junit, to_sarif
from agentfox.evaluation.model_groundedness import ModelGroundednessScorer, model_groundedness
from agentfox.evaluation.ragas_adapter import (
    RAGAS_METRICS,
    RagasSample,
    RagasScores,
    ragas_available,
    score_dataset,
    score_sample,
)
from agentfox.evaluation.redteam import (
    BUILTIN_PROBES,
    NativeRedTeamRunner,
    Probe,
    run_adaptive_probes,
    run_campaign,
)
from agentfox.evaluation.runner import NativeEvalRunner, fit_envelope, sample_production
from agentfox.evaluation.scorers import ScoreContext, ScoreResult, all_scorers, get_scorer, register_scorer
from agentfox.evaluation.silent_failure import (
    SILENT_FAILURE_SCORERS,
    Envelope,
    groundedness,
    self_consistency,
)

__all__ = [
    "BUILTIN_PROBES",
    "OPERATORS",
    "SCOPE_STATEMENT",
    "RAGAS_METRICS",
    "RagasSample",
    "RagasScores",
    "ragas_available",
    "score_dataset",
    "score_sample",
    "SILENT_FAILURE_SCORERS",
    "DriftReport",
    "Envelope",
    "GateResult",
    "NativeEvalRunner",
    "NativeRedTeamRunner",
    "Probe",
    "PromptfooRunner",
    "Regression",
    "ScoreContext",
    "ScoreResult",
    "adaptive",
    "adapters",
    "all_scorers",
    "compute_drift",
    "deployment_profile",
    "drift",
    "evaluate_slos",
    "fit_envelope",
    "gate",
    "gating",
    "get_runner",
    "generate_deployment_probes",
    "get_scorer",
    "groundedness",
    "ks_statistic",
    "ModelGroundednessScorer",
    "model_groundedness",
    "mutation_classes",
    "psi",
    "redteam",
    "register_scorer",
    "run_adaptive_probes",
    "run_campaign",
    "runner",
    "sample_production",
    "scorers",
    "self_consistency",
    "set_baseline",
    "set_slo",
    "silent_failure",
    "to_junit",
    "to_sarif",
]
