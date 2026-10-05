"""Pillar 4 — scorers, silent-failure detection, gating, drift, red team."""

from __future__ import annotations

import pytest

from agentfox.core.models import EvalSuite
from agentfox.evaluation import evaluate_slos, gate, psi, run_campaign, set_baseline, set_slo
from agentfox.evaluation.drift import ks_statistic
from agentfox.evaluation.gating import to_junit, to_sarif
from agentfox.evaluation.model_groundedness import model_groundedness
from agentfox.evaluation.runner import NativeEvalRunner
from agentfox.evaluation.scorers import ScoreContext, get_scorer
from agentfox.evaluation.silent_failure import (
    Envelope,
    SilentFailureScorer,
    groundedness,
    self_consistency,
)
from agentfox.providers import register_provider

from .conftest import as_user

CONTEXT = (
    "Refund policy. Customers may request a refund within 30 days of purchase. "
    "Refunds are issued to the original payment method."
)


def ctx(**kwargs) -> ScoreContext:
    base = {"context": {"retrieved": CONTEXT}}
    base.update(kwargs)
    return ScoreContext(**base)


# ---------------------------------------------------------------------------
# Groundedness (P4-3a)
# ---------------------------------------------------------------------------


def test_grounded_claim_supported():
    assert groundedness("Refunds are issued to the original payment method.", CONTEXT).score == 1.0


def test_wrong_number_is_unsupported():
    """The classic silent failure: right vocabulary, wrong fact."""
    report = groundedness("The refund window is 90 days from purchase.", CONTEXT)
    assert report.score == 0.0
    assert "90" in report.unsupported[0]


def test_fabricated_detail_is_unsupported():
    report = groundedness("Refunds are issued as store credit vouchers only.", CONTEXT)
    assert report.score < 1.0


def test_no_context_is_not_a_failure():
    assert groundedness("anything at all here", "").score == 1.0


def test_numbers_present_in_context_are_fine():
    assert groundedness("You have 30 days.", CONTEXT).score == 1.0


# ---------------------------------------------------------------------------
# Model-based groundedness — the second opinion `groundedness()` above cannot be,
# by its own docstring's admission (grounding, not entailment: a paraphrased
# fabrication scores as fully supported)
# ---------------------------------------------------------------------------


def test_model_groundedness_with_no_context_is_not_a_failure():
    """Same reading as the lexical scorer: nothing to be grounded against, and
    nothing a judge could check either."""
    result = model_groundedness("anything at all here", "")
    assert result["score"] == 1.0


def test_model_groundedness_is_selectable_as_a_scorer():
    """Registered alongside `groundedness`, not folded into it — an eval suite can
    run both and see where they disagree."""
    scorer = get_scorer("model_groundedness")
    assert scorer is not None
    result = scorer.score("Refunds are issued to the original payment method.", ctx())
    assert 0.0 <= result.score <= 1.0
    assert result.detail["judge_model"] == "echo:deterministic"


def test_model_groundedness_uses_the_pinned_offline_judge_by_default():
    """Offline, the judge is the deterministic `echo` provider — same contract
    `LlmJudgeScorer` already established, reused rather than reinvented here."""
    result = model_groundedness("Refunds are issued to the original payment method.", CONTEXT)
    assert result["judge_model"] == "echo:deterministic"
    assert "not a substitute for a model judge" in result["rationale"].lower()


def test_model_groundedness_delegates_to_a_configured_provider():
    """The wiring, proven with a fake provider standing in for a real model: the
    judge's own verdict flows straight through, unmodified."""

    class FakeJudge:
        key = "fake-judge"

        def available(self):
            return True

        def supports_native_streaming(self):
            return False

        def complete(self, request):
            raise NotImplementedError

        def stream(self, request):
            raise NotImplementedError

        def judge(self, output, rubric, model="default"):
            assert CONTEXT in rubric, "the rubric must actually carry the context"
            return {"score": 0.42, "rationale": "a real model would explain itself here"}

    register_provider(FakeJudge())
    result = model_groundedness(
        "Refunds are issued to the original payment method.",
        CONTEXT,
        judge_model="fake-judge:v1",
    )
    assert result["score"] == 0.42
    assert result["judge_model"] == "fake-judge:v1"
    assert "a real model" in result["rationale"]


def test_model_groundedness_falls_back_to_lexical_when_the_judge_call_fails():
    """A scoring signal that can crash an eval run is worse than a weaker one."""

    class BrokenJudge:
        key = "broken-judge"

        def available(self):
            return True

        def supports_native_streaming(self):
            return False

        def complete(self, request):
            raise NotImplementedError

        def stream(self, request):
            raise NotImplementedError

        def judge(self, output, rubric, model="default"):
            raise RuntimeError("judge is down")

    register_provider(BrokenJudge())
    lexical = groundedness("The refund window is 90 days from purchase.", CONTEXT)
    result = model_groundedness(
        "The refund window is 90 days from purchase.", CONTEXT, judge_model="broken-judge:v1"
    )
    assert result["judge_model"] == "native-lexical"
    assert result["score"] == lexical.score
    assert "judge call failed" in result["rationale"]


# ---------------------------------------------------------------------------
# Self-consistency (P4-3b)
# ---------------------------------------------------------------------------


def test_self_consistency_high_for_identical_samples():
    score, _ = self_consistency(["the answer is 30 days"] * 3)
    assert score == pytest.approx(1.0)


def test_self_consistency_low_for_divergent_samples():
    score, detail = self_consistency(
        ["the window is 30 days", "refunds take six months", "we do not offer refunds"]
    )
    assert score < 0.6
    assert detail["n"] == 3


def test_self_consistency_not_evaluated_with_one_sample():
    score, detail = self_consistency(["only one"])
    assert score == 1.0
    assert "not evaluated" in detail["note"]


# ---------------------------------------------------------------------------
# The ensemble (P4-3)
# ---------------------------------------------------------------------------


def test_ensemble_passes_a_correct_answer():
    result = SilentFailureScorer().score("You may request a refund within 30 days.", ctx())
    assert result.passed
    assert result.detail["verdict"] == "no_strong_signal"


def test_ensemble_flags_confident_and_wrong():
    result = SilentFailureScorer().score(
        "Our refund window is 90 days and refunds arrive as store credit.", ctx()
    )
    assert not result.passed
    assert result.detail["verdict"] == "likely_silent_failure"


def test_groundedness_alone_can_trip_the_ensemble():
    """A wholly ungrounded factual claim must not need a second signal to agree."""
    result = SilentFailureScorer().score("The refund window is 365 days.", ctx())
    assert not result.passed


def test_refusal_is_not_a_silent_failure():
    """A visible refusal is a working system; scoring it would flood the queue."""
    result = SilentFailureScorer().score("I cannot help with that request.", ctx())
    assert result.passed
    assert result.detail["verdict"] == "refusal"


def test_hedging_detected():
    scorer = get_scorer("hedging")
    hedged = scorer.score("I think it's probably around 30 days, but I'm not sure.", ctx())
    plain = scorer.score("The refund window is 30 days.", ctx())
    assert hedged.score > plain.score


def test_task_completion_does_not_punish_correct_answers():
    """A goal is written as an instruction; a correct answer restates none of it."""
    scorer = get_scorer("task_completion")
    result = scorer.score(
        "You may request a refund within 30 days of purchase.",
        ctx(expected={"contains": ["30 days"], "goal": "state the refund window"}),
    )
    assert result.passed and result.score == 1.0


def test_task_completion_flags_incompletion():
    scorer = get_scorer("task_completion")
    result = scorer.score(
        "I was unable to complete the lookup. Please provide more information.",
        ctx(expected={"goal": "look up the order"}),
    )
    assert not result.passed


def test_behavioural_envelope():
    envelope = Envelope.fit([100] * 20 + [105, 95], latencies=[50] * 20)
    assert envelope.deviations(102) == []
    assert envelope.deviations(9000)


# ---------------------------------------------------------------------------
# Runner + gating (P4-1)
# ---------------------------------------------------------------------------


def test_runner_scores_every_case(seeded):
    suite = seeded.query(EvalSuite).filter_by(key="support-quality").one()
    run = NativeEvalRunner().run(
        seeded,
        suite,
        {"provider": "echo", "model": "echo-1"},
        ["groundedness", "silent_failure", "contains"],
    )
    assert run.status == "completed"
    assert run.summary_json["cases"] == 5
    assert set(run.summary_json["scorers"]) == {"groundedness", "silent_failure", "contains"}


def test_gate_passes_against_itself(seeded):
    suite = seeded.query(EvalSuite).filter_by(key="support-quality").one()
    run = NativeEvalRunner().run(seeded, suite, {"provider": "echo", "model": "echo-1"})
    set_baseline(seeded, run, "main")
    assert gate(seeded, run, run.id).passed


def test_gate_respects_scorer_direction(seeded):
    """`silent_failure` is lower-is-better; treating a rise as an improvement would
    gate on exactly the wrong thing."""
    from agentfox.core.models import EvalResult

    suite = seeded.query(EvalSuite).filter_by(key="support-quality").one()
    baseline = NativeEvalRunner().run(
        seeded, suite, {"provider": "echo", "model": "echo-1"}, ["silent_failure"]
    )
    current = NativeEvalRunner().run(
        seeded, suite, {"provider": "echo", "model": "echo-1"}, ["silent_failure"]
    )
    # Simulate the agent getting worse: silent-failure risk rises.
    for row in seeded.query(EvalResult).filter_by(run_id=current.id):
        row.score = min(1.0, row.score + 0.5)
    seeded.flush()

    result = gate(seeded, current, baseline.id)
    assert not result.passed
    assert any(r.scorer_key == "silent_failure" for r in result.regressions)


def test_gate_absolute_floor_without_baseline(seeded):
    suite = seeded.query(EvalSuite).filter_by(key="support-quality").one()
    run = NativeEvalRunner().run(
        seeded, suite, {"provider": "echo", "model": "echo-1"}, ["groundedness"]
    )
    result = gate(seeded, run, min_pass_rate=1.0)
    assert not result.passed
    assert result.absolute_failures


def test_gate_reports_are_wellformed(seeded):
    suite = seeded.query(EvalSuite).filter_by(key="support-quality").one()
    run = NativeEvalRunner().run(seeded, suite, {"provider": "echo", "model": "echo-1"})
    result = gate(seeded, run, min_pass_rate=1.0)

    junit = to_junit(result, "support-quality")
    assert "<testsuite" in junit and 'name="support-quality"' in junit

    import json

    sarif = json.loads(to_sarif(result))
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "AgentFox"
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Drift (P4-2)
# ---------------------------------------------------------------------------


def test_psi_zero_for_identical_distributions():
    values = [0.1 * i for i in range(50)]
    assert psi(values, list(values)) == pytest.approx(0.0, abs=1e-9)


def test_psi_rises_on_shift():
    baseline = [0.9] * 50
    shifted = [0.2] * 50
    assert psi(baseline, shifted) > 0.25


def test_ks_statistic():
    assert ks_statistic([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)
    assert ks_statistic([1, 1, 1], [9, 9, 9]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# SLOs (P4-7)
# ---------------------------------------------------------------------------


def test_declaring_an_slo_with_no_data_reports_no_data(seeded):
    """A page that reads SLOs is a dead end without a way to declare one — this is
    the write side that GET /api/eval/slos needs something to show."""
    set_slo(
        seeded,
        agent_slug="support-triage",
        scorer_key="groundedness",
        objective="95% of answers stay grounded",
        target=0.95,
    )
    [reported] = evaluate_slos(seeded, "support-triage")
    assert reported["status"] == "no_data"
    assert reported["agent"] == "support-triage"
    assert reported["scorer"] == "groundedness"


def test_declaring_the_same_pair_twice_edits_rather_than_duplicates(seeded):
    set_slo(seeded, agent_slug="support-triage", scorer_key="groundedness", target=0.9)
    set_slo(seeded, agent_slug="support-triage", scorer_key="groundedness", target=0.99)
    assert len(evaluate_slos(seeded, "support-triage")) == 1
    assert evaluate_slos(seeded, "support-triage")[0]["slo_id"]


def test_the_slo_api(client):
    headers = as_user("priya@example.com")
    created = client.post(
        "/api/eval/slos",
        json={
            "agent": "support-triage",
            "scorer": "groundedness",
            "objective": "95% of answers stay grounded",
            "target": 0.95,
        },
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["agent"] == "support-triage"

    listed = client.get("/api/eval/slos", headers=headers).json()
    assert any(s["agent"] == "support-triage" for s in listed["slos"])

    unknown_agent = client.post(
        "/api/eval/slos",
        json={"agent": "no-such-agent", "scorer": "groundedness"},
        headers=headers,
    )
    assert unknown_agent.status_code == 404


# ---------------------------------------------------------------------------
# Red team (P4-4)
# ---------------------------------------------------------------------------


def test_campaign_produces_posture(seeded):
    campaign = run_campaign(seeded, "support-triage")
    summary = campaign.summary_json
    assert summary["probes_run"] > 0
    assert 0.0 <= summary["posture_score"] <= 1.0
    assert 0.0 <= summary["recall"] <= 1.0
    assert 0.0 <= summary["precision"] <= 1.0
    # probes_run now splits into real attacks (recall side) and benign controls
    # (precision side) — the two must sum back to the total, not collapse into a
    # single "blocked vs succeeded" pair the way they did before benign_control
    # probes existed.
    assert summary["attacks_blocked"] + summary["attacks_succeeded"] == summary["attacks_run"]
    assert summary["attacks_run"] + summary["benign_probes_run"] == summary["probes_run"]
    assert "prompt_injection" in summary["by_category"]
    assert "benign_control" in summary["by_category"]


def test_campaign_blocks_injection_probes_when_enforcing(seeded):
    from agentfox.policy import set_mode

    set_mode(seeded, "baseline", "enforce")
    campaign = run_campaign(
        seeded, "support-triage", probes=["prompt_injection", "data_exfiltration"]
    )
    assert campaign.summary_json["attacks_succeeded"] == 0


def test_campaigns_are_static_unless_adaptive_is_asked_for(seeded):
    """Adaptive mode (`evaluation/adaptive.py`) is opt-in. This pins the default from
    the Pillar-4 suite as well as from the adaptive suite, because the default is what
    CI and `agentfox redteam run` call and the cost of it flipping silently is a
    campaign that mutates and retries where an operator expected a fixed list."""
    campaign = run_campaign(seeded, "support-triage")
    assert "adaptive" not in campaign.summary_json
    assert "posture" not in campaign.summary_json

    adaptive = run_campaign(seeded, "support-triage", adaptive=True, budget=2)
    assert adaptive.summary_json["adaptive"]["budget"] == 2
    # The honest claim travels with the result, not only with the docs.
    assert "not adversarial robustness" in adaptive.summary_json["what_this_measures"]


def test_campaign_breach_raises_a_finding(seeded):
    from agentfox.core.models import Finding

    run_campaign(seeded, "support-triage")
    findings = seeded.query(Finding).filter_by(type="redteam").all()
    # Some probes get through in observe mode; that must be reported, not hidden.
    if findings:
        assert "NOM-EVL-04" in findings[0].control_keys


# ---------------------------------------------------------------------------
# Red team: tool_call / scenario probes (P4-4) — the structural extension.
#
# Before this, every probe was `kind="content"`, which only ever reaches
# `Enforcer.check_content()` — and `check_content()` never passes `arguments`/
# `tool_key`, so capability/constraint checks, the action-assurance/SQLi-scope
# backstop, and composed-privilege-escalation (F3.8) were structurally
# unreachable by any probe, not merely weak against them.
# ---------------------------------------------------------------------------


def test_a_tool_call_probe_with_no_grant_is_blocked(seeded):
    from agentfox.policy import set_mode

    set_mode(seeded, "tool-containment", "enforce")
    campaign = run_campaign(seeded, "support-triage", probes=["capability.ungranted_tool"])
    assert campaign.summary_json["attacks_succeeded"] == 0


def test_a_tool_call_probe_violating_a_grant_constraint_is_blocked(seeded):
    from agentfox.policy import set_mode

    set_mode(seeded, "tool-containment", "enforce")
    campaign = run_campaign(seeded, "support-triage", probes=["capability.constraint_violation"])
    assert campaign.summary_json["attacks_succeeded"] == 0


def test_action_assurance_probes_are_reachable_via_guard_tool_call(seeded):
    """These fire `analyse_arguments` (destructive SQL, the scope/SQLi backstop) —
    unreachable via `check_content()` before this round, since it never passes
    `arguments`/`tool_key` at all."""
    from agentfox.policy import set_mode

    set_mode(seeded, "tool-containment", "enforce")
    campaign = run_campaign(
        seeded,
        "support-triage",
        probes=[
            "action.destructive_sql_no_where",
            "action.sql_injection_in_argument",
            "action.wildcard_scope_argument",
        ],
    )
    assert campaign.summary_json["attacks_succeeded"] == 0


def test_the_composed_escalation_scenario_probe_is_blocked(seeded):
    """F3.8 through the red-team runner specifically — a read tool's synthetic
    result feeding a write tool's argument across two real `guard_tool_call`s
    sharing one `TaintTracker`."""
    from agentfox.policy import set_mode

    set_mode(seeded, "tool-containment", "enforce")
    campaign = run_campaign(seeded, "support-triage", probes=["escalation.composed_privilege"])
    assert campaign.summary_json["attacks_succeeded"] == 0


def test_the_composed_escalation_negative_control_is_not_over_blocked(seeded):
    """The same two tools, but the second call's argument never appeared in the
    first call's result — must not be flagged, proving the block above is about
    provenance and not just "any two-step tool sequence on these tools"."""
    from agentfox.policy import set_mode

    set_mode(seeded, "tool-containment", "enforce")
    campaign = run_campaign(seeded, "support-triage", probes=["benign.independently_supplied_id"])
    assert campaign.summary_json["benign_false_positives"] == 0


def test_a_legitimate_call_within_the_same_constraint_is_not_over_blocked(seeded):
    from agentfox.policy import set_mode

    set_mode(seeded, "tool-containment", "enforce")
    campaign = run_campaign(
        seeded,
        "support-triage",
        probes=["capability.constraint_violation", "benign.refund_within_constraint"],
    )
    assert campaign.summary_json["benign_false_positives"] == 0
    assert campaign.summary_json["attacks_succeeded"] == 0
