"""Silent-failure detection (P4-3, NOM-EVL-03).

**The highest-leverage requirement in the PRD, and the category we intend to own.**

The market data is unambiguous: 89–94% of teams have observability, ~52% run offline
evals, 37% run online evals, and 22.8% run none at all — while roughly 78% of AI
failures are "invisible": plausible, confident, and wrong. The gap is not that teams
cannot *see* their agents. It is that they cannot *judge* them. No OSS project in the
catalog addresses this (Appendix A.5), and it is what lets a governance product claim
it governs **correctness**, not merely safety — the line between us and every
pure-security vendor.

Six signal families, ensembled:

  (a) **groundedness**      — claims unsupported by the retrieved context
  (b) **self-consistency**  — divergence across resampled generations
  (c) **contract violation** — declared schema, format or invariant broken
  (d) **behavioural anomaly** — length / latency / tool-sequence outside the envelope
  (e) **hedging**           — uncertainty markers signalling a guess dressed as fact
  (f) **task completion**   — the agent stopped without satisfying the declared goal

None is decisive alone; that is the point. Each is a weak signal, and the ensemble is
what turns "the output looked fine" into a number an SLO can be written against.
"""

from __future__ import annotations

import difflib
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from agentfox.evaluation.scorers import (
    BaseScorer,
    ScoreContext,
    ScoreResult,
    content_tokens,
    register_scorer,
    sentences,
)

# (e) Hedging markers — a model signalling low confidence in prose.
_HEDGES = [
    r"\bi'?m not (?:entirely |completely |100% )?(?:sure|certain)\b",
    r"\bi (?:believe|think|assume|suspect|guess)\b",
    r"\bit (?:appears|seems|looks like)\b",
    r"\b(?:probably|possibly|presumably|perhaps|maybe|likely)\b",
    r"\bmay (?:be|have|not)\b",
    r"\bcould (?:be|have)\b",
    r"\bas far as i (?:know|can tell)\b",
    r"\bwithout (?:more|additional) (?:context|information)\b",
    r"\bi don'?t have (?:access|enough)\b",
]
_HEDGE_RE = [re.compile(p, re.I) for p in _HEDGES]

# (f) Incompletion markers — the agent narrating a stop rather than finishing.
_INCOMPLETE = [
    r"\bi (?:was )?(?:unable|can'?t|cannot|couldn'?t) (?:to )?(?:complete|finish|do|access)\b",
    r"\b(?:let me know if|you (?:may|might|should)) (?:want|need|try)\b",
    r"\bplease (?:provide|supply|share) (?:more|the|additional)\b",
    r"\bTODO\b|\bplaceholder\b|\b\[insert\b",
    r"\.\.\.$",
]
_INCOMPLETE_RE = [re.compile(p, re.I) for p in _INCOMPLETE]

# Refusals, which are *not* silent failures — a visible refusal is a working system.
_REFUSAL_RE = [
    re.compile(r"\bi (?:can'?t|cannot|won'?t) (?:help|assist|provide|comply)\b", re.I),
    re.compile(r"\b(?:against|violates) (?:my|our) (?:policy|guidelines)\b", re.I),
]


# ---------------------------------------------------------------------------
# (a) Groundedness
# ---------------------------------------------------------------------------


@dataclass
class GroundednessReport:
    score: float = 1.0
    supported: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "unsupported_claims": self.unsupported[:10],
            "supported_count": len(self.supported),
            "unsupported_count": len(self.unsupported),
        }


def groundedness(output: str, context_text: str, min_overlap: float = 0.6) -> GroundednessReport:
    """Fraction of the output's factual sentences supported by the context.

    Two checks per claim, because lexical overlap alone is not enough — the classic
    silent failure is an answer that *reuses the context's vocabulary* while changing
    the fact ("the refund window is **90** days", "refunds are issued as **store
    credit**"). Overlap scores that highly; a reader would not.

      1. **Numeric agreement.** Any figure asserted in the claim that does not appear
         in the context makes the claim unsupported outright. Numbers are where
         confidently-wrong answers usually go wrong, and they are cheap to check.
      2. **Lexical support.** The remaining content tokens must overlap the context
         above ``min_overlap``.

    This is grounding, not entailment: it will not catch a fabricated claim phrased
    entirely in the context's own words and numbers. That is why it is one member of
    an ensemble and never a standalone verdict — a groundedness score presented as
    truth would itself be the confident-and-wrong failure this module exists to catch.
    """
    from agentfox.evaluation.scorers import numeric_tokens

    report = GroundednessReport()
    if not context_text.strip():
        return report  # nothing to be grounded against; not a failure

    supporting = content_tokens(context_text)
    supporting_numbers = numeric_tokens(context_text)
    claims = [s for s in sentences(output) if len(content_tokens(s)) >= 3]
    if not claims:
        return report

    for claim in claims:
        claim_tokens = content_tokens(claim)
        if not claim_tokens:
            continue

        unmatched_numbers = numeric_tokens(claim) - supporting_numbers
        if unmatched_numbers:
            report.unsupported.append(
                f"{claim[:180]}  [figures not in context: {', '.join(sorted(unmatched_numbers))}]"
            )
            continue

        overlap = len(claim_tokens & supporting) / len(claim_tokens)
        if overlap >= min_overlap:
            report.supported.append(claim[:200])
        else:
            missing = sorted(claim_tokens - supporting)[:6]
            report.unsupported.append(
                f"{claim[:180]}  [overlap {overlap:.2f}; unsupported terms: {', '.join(missing)}]"
            )

    total = len(report.supported) + len(report.unsupported)
    report.score = (len(report.supported) / total) if total else 1.0
    return report


# ---------------------------------------------------------------------------
# (b) Self-consistency
# ---------------------------------------------------------------------------


def self_consistency(samples: list[str]) -> tuple[float, dict[str, Any]]:
    """Mean pairwise similarity across resampled generations.

    A model that answers the same question three different ways is guessing. This is
    the cheapest reliable hallucination signal that needs no ground truth — which is
    what makes it usable on production traffic where ground truth never exists.
    """
    usable = [s for s in samples if s and s.strip()]
    if len(usable) < 2:
        return 1.0, {"note": "fewer than two samples; not evaluated", "n": len(usable)}

    ratios: list[float] = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            ratios.append(
                difflib.SequenceMatcher(None, usable[i].lower(), usable[j].lower()).ratio()
            )
    mean = statistics.fmean(ratios)
    return mean, {
        "n": len(usable),
        "pairs": len(ratios),
        "mean_similarity": round(mean, 3),
        "min_similarity": round(min(ratios), 3),
        "stdev": round(statistics.pstdev(ratios), 3) if len(ratios) > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# (d) Behavioural envelope
# ---------------------------------------------------------------------------


@dataclass
class Envelope:
    """Learned from observed traffic. Statistical, not ML — deliberately.

    An interpretable envelope can be shown to an auditor and argued with. A learned
    model that flags an agent as anomalous without a reason is not evidence.
    """

    length_mean: float = 0.0
    length_stdev: float = 0.0
    latency_p95: float = 0.0
    tool_count_mean: float = 0.0
    n: int = 0

    @classmethod
    def fit(
        cls,
        lengths: list[int],
        latencies: list[float] | None = None,
        tool_counts: list[int] | None = None,
    ) -> Envelope:
        latencies = latencies or []
        tool_counts = tool_counts or []
        env = cls(n=len(lengths))
        if lengths:
            env.length_mean = statistics.fmean(lengths)
            env.length_stdev = statistics.pstdev(lengths) if len(lengths) > 1 else 0.0
        if latencies:
            ordered = sorted(latencies)
            env.latency_p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
        if tool_counts:
            env.tool_count_mean = statistics.fmean(tool_counts)
        return env

    def deviations(
        self, length: int, latency_ms: float = 0.0, tool_count: int = 0, sigma: float = 3.0
    ) -> list[str]:
        out: list[str] = []
        if self.n >= 10 and self.length_stdev > 0:
            z = abs(length - self.length_mean) / self.length_stdev
            if z > sigma:
                out.append(
                    f"output length {length} is {z:.1f}σ from the mean {self.length_mean:.0f}"
                )
        if self.latency_p95 and latency_ms > self.latency_p95 * 2:
            out.append(f"latency {latency_ms:.0f}ms is over 2× the observed p95")
        if self.tool_count_mean and tool_count > max(3, self.tool_count_mean * 3):
            out.append(f"{tool_count} tool calls vs a mean of {self.tool_count_mean:.1f}")
        return out


# ---------------------------------------------------------------------------
# Scorers
# ---------------------------------------------------------------------------


class GroundednessScorer(BaseScorer):
    key, kind, threshold = "groundedness", "groundedness", 0.7

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        report = groundedness(output, _context_text(ctx))
        detail = {k: v for k, v in report.to_json().items() if k != "score"}
        return self._result(report.score, **detail)


class SelfConsistencyScorer(BaseScorer):
    key, kind, threshold = "self_consistency", "self_consistency", 0.6

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        samples = ctx.samples or [output]
        score, detail = self_consistency(samples)
        return self._result(score, **detail)


class HedgingScorer(BaseScorer):
    """Higher score = more hedging = worse."""

    key, kind, higher_is_better, threshold = "hedging", "custom", False, 0.3

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        hits = [p.pattern for p in _HEDGE_RE if p.search(output)]
        n_sentences = max(1, len(sentences(output)))
        score = min(1.0, len(hits) / min(n_sentences, 5))
        return self._result(score, markers=len(hits), patterns=hits[:5])


class TaskCompletionScorer(BaseScorer):
    """(f) Did the agent finish the job, or narrate stopping?

    Note what this deliberately does *not* do: score the overlap between the output
    and the goal *statement*. A goal is written as an instruction ("state the refund
    window") and a correct answer restates none of those words — so token overlap
    would mark every good answer as incomplete. That is a heuristic that punishes
    correctness, which is worse than no heuristic.

    Instead: declared content requirements when the case supplies them, and
    incompletion markers otherwise.
    """

    key, kind, threshold = "task_completion", "custom", 0.7

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        if not output.strip():
            return self._result(0.0, reason="empty output")

        # A visible refusal is not a silent failure — the system worked and said so.
        if any(p.search(output) for p in _REFUSAL_RE):
            return self._result(1.0, reason="explicit refusal (visible, not silent)")

        penalties = [p.pattern for p in _INCOMPLETE_RE if p.search(output)]

        # A declared `contains` requirement is a real, checkable completion signal.
        required = ctx.expected.get("contains") or []
        if isinstance(required, str):
            required = [required]
        if required:
            present = [r for r in required if str(r).lower() in output.lower()]
            base = len(present) / len(required)
            missing = [r for r in required if r not in present]
        else:
            base = 1.0
            missing = []

        score = max(0.0, min(1.0, base - 0.35 * len(penalties)))
        goal = str(ctx.case_input.get("goal") or ctx.expected.get("goal") or "")
        return self._result(
            score,
            incompletion_markers=penalties,
            required_missing=missing,
            declared_goal=goal or None,
        )


class SilentFailureScorer(BaseScorer):
    """The ensemble (P4-3). One number, with the contributing signals attached.

    Weighted toward groundedness and consistency because those are the two signals
    that fire on *confidently wrong* output; hedging and incompletion mostly catch
    visibly-degraded output, which teams already notice.
    """

    # Threshold sits below the groundedness weight on purpose: a wholly ungrounded
    # factual claim must be able to trip the ensemble on its own, without needing a
    # second signal to agree.
    key, kind, higher_is_better, threshold = "silent_failure", "custom", False, 0.3

    WEIGHTS = {
        "groundedness": 0.35,
        "self_consistency": 0.25,
        "contract": 0.15,
        "task_completion": 0.15,
        "hedging": 0.10,
    }

    def score(self, output: str, ctx: ScoreContext) -> ScoreResult:
        signals: dict[str, float] = {}
        detail: dict[str, Any] = {}

        # A visible refusal is a working system, not a silent failure. Scoring it as
        # one would flood the queue with the safest outputs the agent produces — and
        # a detector whose top hits are all correct behaviour gets switched off.
        if any(p.search(output) for p in _REFUSAL_RE):
            return self._result(
                0.0,
                verdict="refusal",
                note="explicit refusal — a visible failure mode, excluded from scoring",
            )

        report = groundedness(output, _context_text(ctx))
        signals["groundedness"] = 1.0 - report.score
        detail["groundedness"] = report.to_json()

        consistency, consistency_detail = self_consistency(ctx.samples or [output])
        signals["self_consistency"] = 1.0 - consistency
        detail["self_consistency"] = consistency_detail

        contract = JsonContractSignal().evaluate(output, ctx)
        signals["contract"] = contract["risk"]
        detail["contract"] = contract

        completion = TaskCompletionScorer().score(output, ctx)
        signals["task_completion"] = 1.0 - completion.score
        detail["task_completion"] = completion.detail

        hedging = HedgingScorer().score(output, ctx)
        signals["hedging"] = hedging.score
        detail["hedging"] = hedging.detail

        envelope: Envelope | None = ctx.context.get("envelope")
        if isinstance(envelope, Envelope):
            deviations = envelope.deviations(len(output), ctx.duration_ms, len(ctx.tool_calls))
            detail["behavioural"] = {"deviations": deviations}
            if deviations:
                # Anomaly does not create risk on its own; it amplifies what is there.
                signals = {k: min(1.0, v * 1.2) for k, v in signals.items()}

        risk = sum(signals[k] * w for k, w in self.WEIGHTS.items())
        detail["signals"] = {k: round(v, 3) for k, v in signals.items()}
        detail["weights"] = self.WEIGHTS
        detail["verdict"] = (
            "likely_silent_failure" if risk >= self.threshold else "no_strong_signal"
        )
        return self._result(round(risk, 4), **detail)


class JsonContractSignal:
    """(c) contract violation, expressed as a risk in [0, 1]."""

    def evaluate(self, output: str, ctx: ScoreContext) -> dict[str, Any]:
        schema = ctx.expected.get("schema") or ctx.context.get("schema")
        if not schema:
            return {"risk": 0.0, "note": "no declared contract"}
        from agentfox.evaluation.scorers import JsonSchemaScorer

        result = JsonSchemaScorer().score(output, ctx)
        return {"risk": 1.0 - result.score, "errors": result.detail.get("errors", [])}


def _context_text(ctx: ScoreContext) -> str:
    """Retrieved context for grounding, from wherever the harness put it."""
    for key in ("retrieved", "context", "documents", "sources"):
        value = ctx.context.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            parts = [
                v if isinstance(v, str) else str(v.get("text") or v.get("content") or "")
                for v in value
            ]
            joined = "\n".join(p for p in parts if p)
            if joined.strip():
                return joined
    return ""


for _s in (
    GroundednessScorer(),
    SelfConsistencyScorer(),
    HedgingScorer(),
    TaskCompletionScorer(),
    SilentFailureScorer(),
):
    register_scorer(_s)

SILENT_FAILURE_SCORERS = (
    "groundedness",
    "self_consistency",
    "hedging",
    "task_completion",
    "silent_failure",
)
