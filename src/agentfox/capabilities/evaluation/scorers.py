"""Scorer library.

Deterministic and offline by default. LLM-as-judge exists but pins its
judge model and records the rubric, because a non-reproducible score cannot appear
in an evidence package.

The scorers in :mod:`.silent_failure` are the ones that matter commercially — this
module holds the conventional set they are measured against.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from agentfox.capabilities.detection.detectors.schema import extract_json, validate

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def numeric_tokens(text: str) -> set[str]:
    """Numbers and number-bearing tokens, normalised (``1,000`` -> ``1000``)."""
    out: set[str] = set()
    for match in re.finditer(r"\d[\d,.]*", (text or "")):
        value = match.group().rstrip(".").replace(",", "")
        if value:
            out.add(value.lstrip("0") or "0")
    return out


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


@dataclass
class ScoreResult:
    score: float = 0.0
    passed: bool = True
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreContext:
    """Everything a scorer may consult beyond the output string."""

    case_input: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    samples: list[str] = field(default_factory=list)  # for self-consistency
    tool_calls: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    agent_slug: str | None = None


class Scorer(Protocol):
    key: str
    kind: str
    #: True when a *higher* score is better. Drives regression-gate direction.
    higher_is_better: bool

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult: ...


class BaseScorer:
    key = "base"
    kind = "custom"
    higher_is_better = True
    threshold = 0.5

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        raise NotImplementedError

    def _result(self, score: float, **detail: Any) -> ScoreResult:
        passed = score >= self.threshold if self.higher_is_better else score <= self.threshold
        return ScoreResult(score=score, passed=passed, detail=detail)


# ---------------------------------------------------------------------------
# Conventional correctness
# ---------------------------------------------------------------------------


class ExactMatchScorer(BaseScorer):
    key, kind, threshold = "exact_match", "exact", 1.0

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        expected = str(ctx.expected.get("output", "")).strip()
        return self._result(1.0 if output.strip() == expected else 0.0, expected=expected)


class FuzzyMatchScorer(BaseScorer):
    key, kind, threshold = "fuzzy_match", "fuzzy", 0.8

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        expected = str(ctx.expected.get("output", ""))
        if not expected:
            return self._result(1.0, note="no expected output declared")
        ratio = difflib.SequenceMatcher(
            None, output.strip().lower(), expected.strip().lower()
        ).ratio()
        return self._result(ratio, expected_len=len(expected))


class ContainsScorer(BaseScorer):
    key, kind, threshold = "contains", "custom", 1.0

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        needles = ctx.expected.get("contains") or []
        if isinstance(needles, str):
            needles = [needles]
        if not needles:
            return self._result(1.0)
        hits = [n for n in needles if str(n).lower() in output.lower()]
        return self._result(len(hits) / len(needles), missing=[n for n in needles if n not in hits])


class RegexScorer(BaseScorer):
    key, kind, threshold = "regex", "regex", 1.0

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        pattern = ctx.expected.get("pattern")
        if not pattern:
            return self._result(1.0)
        return self._result(1.0 if re.search(pattern, output) else 0.0, pattern=pattern)


class JsonSchemaScorer(BaseScorer):
    key, kind, threshold = "json_schema", "json_schema", 1.0

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        schema = ctx.expected.get("schema") or ctx.context.get("schema")
        if not schema:
            return self._result(1.0)
        parsed = extract_json(output)
        if parsed is None:
            return self._result(0.0, errors=["output is not valid JSON"])
        errors = validate(parsed, schema)
        return self._result(0.0 if errors else 1.0, errors=errors[:10])


# ---------------------------------------------------------------------------
# Operational
# ---------------------------------------------------------------------------


class LatencyScorer(BaseScorer):
    key, kind, higher_is_better = "latency", "latency", False

    def __init__(self, budget_ms: float = 5000) -> None:
        self.threshold = budget_ms

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        return self._result(ctx.duration_ms, budget_ms=self.threshold)


class CostScorer(BaseScorer):
    key, kind, higher_is_better = "cost", "cost", False

    def __init__(self, budget_usd: float = 0.05) -> None:
        self.threshold = budget_usd

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        return self._result(ctx.cost_usd, budget_usd=self.threshold)


class ToolTrajectoryScorer(BaseScorer):
    """Did the agent take the expected path, not merely reach the answer?

    A right answer via the wrong tools is a governance problem even when it is not
    a correctness problem — it means the capability model does not match reality.
    """

    key, kind, threshold = "tool_trajectory", "tool_trajectory", 0.8

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        expected = ctx.expected.get("tools") or []
        if not expected:
            return self._result(1.0)
        actual = ctx.tool_calls
        matcher = difflib.SequenceMatcher(None, expected, actual)
        unexpected = [t for t in actual if t not in expected]
        return self._result(
            matcher.ratio(), expected=expected, actual=actual, unexpected=unexpected
        )


class SafetyScorer(BaseScorer):
    """Runs the guardrail pipeline as a scorer, so eval and runtime agree.

    Reusing the same detectors means a case that passes evaluation cannot be
    blocked at runtime by a rule the eval never saw.
    """

    key, kind, higher_is_better, threshold = "safety", "safety", False, 0.5

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        from agentfox.capabilities.detection import DetectionContext, DetectorPipeline

        result = DetectorPipeline().run(output, DetectionContext(surface="output"))
        return self._result(
            result.max_score,
            entities=sorted(result.by_entity()),
            detectors=[r.detector_key for r in result.results],
        )


class LlmJudgeScorer(BaseScorer):
    """LLM-as-judge with a pinned model and a recorded rubric.

    Offline, the pinned judge is the deterministic ``echo`` provider, which scores
    by rubric-keyword coverage. That is honest: a judge you cannot reproduce should
    not silently become a compliance artefact.
    """

    key, kind, threshold = "llm_judge", "llm_judge", 0.7

    def __init__(self, rubric: str = "", judge_model: str = "echo:deterministic") -> None:
        self.rubric = rubric
        self.judge_model = judge_model

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        from agentfox.platform.providers import get_provider

        provider_key, _, model = self.judge_model.partition(":")
        provider = get_provider(provider_key)
        rubric = self.rubric or str(ctx.expected.get("rubric", ""))
        verdict = provider.judge(output=output, rubric=rubric, model=model or "default")
        return self._result(
            verdict["score"],
            judge_model=self.judge_model,
            rubric=rubric,
            rationale=verdict.get("rationale", ""),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_SCORERS: dict[str, Scorer] = {}


def register_scorer(scorer: Scorer) -> Scorer:
    _SCORERS[scorer.key] = scorer
    return scorer


def get_scorer(key: str) -> Scorer | None:
    return _SCORERS.get(key)


def all_scorers() -> dict[str, Scorer]:
    return dict(_SCORERS)


def unknown_scorers(keys: list[str] | tuple[str, ...]) -> list[str]:
    """The keys in ``keys`` no scorer is registered under, in the order given."""
    return [key for key in keys if key not in _SCORERS]


for _s in (
    ExactMatchScorer(),
    FuzzyMatchScorer(),
    ContainsScorer(),
    RegexScorer(),
    JsonSchemaScorer(),
    LatencyScorer(),
    CostScorer(),
    ToolTrajectoryScorer(),
    SafetyScorer(),
    LlmJudgeScorer(),
):
    register_scorer(_s)
