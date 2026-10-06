"""Business-process guardrails, and the catalogue that makes new ones cheap to write.

The security guardrails in :mod:`agentfox.capabilities.detection` answer "may this happen at all".
This package answers the other question a business actually asks — *"under which
circumstances, and who has to agree"* — and the two compose by different algebras,
which is the whole architectural point. See :mod:`agentfox.business.graph`.
"""

from __future__ import annotations

from agentfox.business.catalogue import CATALOGUE, GuardrailKind, by_intent, inert_kinds, suggest
from agentfox.business.catalogue import to_json as catalogue_json
from agentfox.business.graph import (
    CombinedDecision,
    Conflict,
    GraphNode,
    build_graph,
    combine,
    find_conflicts,
)
from agentfox.business.ladder import (
    Band,
    Ladder,
    LadderDecision,
    VerifyResult,
    VerifySpec,
    run_verification,
)
from agentfox.business.ladder import evaluate as evaluate_ladder
from agentfox.business.store import all_ladders, load_ladders, save_ladder, set_mode, summary

__all__ = [
    "CATALOGUE",
    "Band",
    "CombinedDecision",
    "Conflict",
    "GraphNode",
    "GuardrailKind",
    "Ladder",
    "LadderDecision",
    "VerifyResult",
    "VerifySpec",
    "run_verification",
    "build_graph",
    "by_intent",
    "catalogue_json",
    "combine",
    "evaluate_ladder",
    "find_conflicts",
    "inert_kinds",
    "suggest",
    "all_ladders",
    "load_ladders",
    "save_ladder",
    "set_mode",
    "summary",
]
