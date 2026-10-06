"""Adaptive red-team campaigns — the mutation loop, deployment targeting, posture.

What these tests are actually defending, in order of how easy each would be to
quietly break:

* **The static default is unchanged.** `adaptive` defaults to False and that path
  must behave exactly as it did before this module existed, because it is what CI
  and `agentfox redteam run` call today.
* **Adaptive genuinely adapts.** The bar is not "it ran more probes": it is that
  mutation finds at least one escape the static suite does not, on the real seeded
  configuration with policies enforcing.
* **It is reproducible.** A red-team number nobody can re-derive is not evidence.
  Same seed, same configuration, same mutations and same verdicts.
* **It is bounded.** A per-probe attempt budget that silently doesn't hold turns a
  CI step into an unbounded search.
* **It never edits what it measures.** Deployment-derived probes must not create a
  tool row or a capability grant.
* **It never claims robustness.** The scope statement is load-bearing product
  honesty, not decoration, so it is asserted like any other behaviour.
"""

from __future__ import annotations

import pytest

from agentfox.capabilities.evaluation.adaptive import (
    NOT_ESTABLISHED,
    OPERATORS,
    SCOPE_STATEMENT,
    deployment_profile,
    generate_deployment_probes,
    mutation_classes,
    next_mutation,
    rank_classes,
)
from agentfox.capabilities.evaluation.redteam import BUILTIN_PROBES, ProbeOutcome, run_campaign


@pytest.fixture
def enforcing(seeded):
    """The configuration an adaptive campaign is supposed to be run against: real
    seed agents with the shipped policy packs actually enforcing. Running adaptive
    against observe-mode policies would let almost everything through and prove
    nothing about mutation."""
    from agentfox.platform.policy import set_mode

    set_mode(seeded, "baseline", "enforce")
    set_mode(seeded, "tool-containment", "enforce")
    return seeded


# ---------------------------------------------------------------------------
# The static default must not move
# ---------------------------------------------------------------------------


def test_static_campaign_is_unchanged_by_default(enforcing):
    """No adaptive key, no posture key, one outcome per built-in probe, and the
    summary shape the CLI already renders."""
    campaign = run_campaign(enforcing, "support-triage")
    summary = campaign.summary_json

    assert "adaptive" not in summary
    assert "posture" not in summary
    assert campaign.target_json == {"agent": "support-triage"}
    assert summary["probes_run"] == len(BUILTIN_PROBES)
    assert campaign.probes == [p.key for p in BUILTIN_PROBES]
    for key in ("recall", "precision", "posture_score", "by_category", "probes"):
        assert key in summary
    # Every recorded probe is a first (and only) attempt with no mutation lineage.
    assert {p["attempt"] for p in summary["probes"]} == {1}
    assert all(p["mutation_chain"] == [] for p in summary["probes"])


def test_budget_of_one_is_exactly_the_static_suite(enforcing):
    """`budget=1` means "the original attempt and nothing else", so adaptive mode
    with no budget must reproduce the static attack result. If this drifts, the
    budget is not really counting the original attempt and every reported
    `attempts_used` is off by one."""
    static = run_campaign(enforcing, "support-triage", name="s")
    adaptive = run_campaign(
        enforcing,
        "support-triage",
        name="a",
        adaptive=True,
        budget=1,
        include_deployment_probes=False,
    )
    assert adaptive.summary_json["adaptive"]["attempts_used"] == len(BUILTIN_PROBES)
    assert adaptive.summary_json["adaptive"]["mutated_attempts"] == 0
    assert adaptive.summary_json["attacks_succeeded"] == static.summary_json["attacks_succeeded"]


# ---------------------------------------------------------------------------
# Adaptive has to actually find something static misses
# ---------------------------------------------------------------------------


def test_adaptive_finds_escapes_the_static_suite_misses(enforcing):
    """The headline claim of the feature. Same probes, same enforcing configuration
    — the only difference is that a blocked probe gets mutated and retried."""
    static = run_campaign(enforcing, "support-triage", name="static")
    static_escapes = {p["key"] for p in static.summary_json["probes"] if p["succeeded"]}

    campaign = run_campaign(
        enforcing,
        "support-triage",
        name="adaptive",
        adaptive=True,
        budget=4,
        include_deployment_probes=False,
    )
    adaptive = campaign.summary_json["adaptive"]
    new = set(adaptive["escaping_probes"]) - static_escapes
    assert new, "adaptive mode found nothing the static suite missed"
    # And every one of them was found *by a mutation*, not by the unmutated probe.
    assert all(e["mutation_chain"] for e in adaptive["escapes"] if e["origin"] in new)
    assert adaptive["mutation_classes_that_worked"]


def test_a_working_mutation_class_is_surfaced_as_a_finding(enforcing):
    """ "Encoding defeats this deployment" is an actionable sentence; "escape rate 4%"
    is the shape that lets a real gap ship as a KPI. It must be a Finding."""
    from agentfox.core.models import Finding

    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=4)
    worked = campaign.summary_json["adaptive"]["mutation_classes_that_worked"]
    assert worked
    findings = enforcing.query(Finding).filter_by(type="redteam_mutation_class").all()
    assert findings
    assert all(cls in findings[0].title for cls in worked)


def test_mutations_are_chosen_from_the_failure_feedback(enforcing):
    """Not "it mutated" but "it mutated *because of what fired*". A taint rule should
    steer towards provenance/argument mutations, an injection detection towards
    encoding/obfuscation ones — otherwise this is a random search wearing a hat."""
    probe = next(p for p in BUILTIN_PROBES if p.kind == "tool_call")
    taint_feedback = ProbeOutcome(
        probe=probe,
        blocked=True,
        verdict="block",
        detail={"rules_fired": [{"rule_id": "taint.irreversible_tool"}]},
    )
    assert rank_classes(taint_feedback, "tool_call")[0] == "provenance"

    content_probe = next(p for p in BUILTIN_PROBES if p.kind == "content")
    injection_feedback = ProbeOutcome(
        probe=content_probe,
        blocked=True,
        verdict="block",
        detections=["INJECTION.DIRECT_OVERRIDE"],
        detail={"rules_fired": [{"rule_id": "injection.direct"}]},
    )
    assert rank_classes(injection_feedback, "content")[0] == "encoding"
    # And the ranking is only over classes that can apply to that probe kind.
    assert "provenance" not in rank_classes(injection_feedback, "content")
    assert "encoding" not in rank_classes(taint_feedback, "tool_call")


# ---------------------------------------------------------------------------
# Budget and determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("budget", [1, 2, 3])
def test_attempt_budget_is_respected_per_probe(enforcing, budget):
    from agentfox.core.models import RedTeamFinding

    campaign = run_campaign(
        enforcing, "support-triage", adaptive=True, budget=budget, name=f"b{budget}"
    )
    rows = enforcing.query(RedTeamFinding).filter_by(campaign_id=campaign.id).all()
    per_origin: dict[str, int] = {}
    for row in rows:
        origin = row.evidence_json.get("origin") or row.probe
        per_origin[origin] = per_origin.get(origin, 0) + 1
        assert row.evidence_json["attempt"] <= budget
    assert per_origin
    assert max(per_origin.values()) <= budget


def test_a_probe_stops_early_once_it_escapes(enforcing):
    """Budget is a ceiling, not a quota: once an attack is through, there is nothing
    left to learn from spending the rest of it."""
    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=5)
    adaptive = campaign.summary_json["adaptive"]
    assert adaptive["attempts_used"] < adaptive["seed_probes"] * 5


@pytest.fixture
def no_timing_flake(monkeypatch):
    """Removes the one source of run-to-run variation that is not ours.

    The detector pipeline enforces a per-detector timeout (40ms by default); a
    detector that trips it is recorded as `degraded`, and `baseline.yaml`'s
    `pipeline.degraded_high_risk` escalates any high-risk agent's request when that
    happens. That is wall-clock dependent, so a large payload can flip a verdict
    between two otherwise identical runs — observed exactly once, on `payments-ops`
    (the only high-risk seed agent), with a 1.5KB hex payload. It is a real property
    of the product and is disclosed in benchmarks/redteam/README.md rather than
    hidden. What *this* module promises is that the mutation search is deterministic,
    so the timeout is raised out of the way here to test that claim rather than the
    pipeline's clock."""
    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("NOMETRIA_DETECTOR_TIMEOUT_MS", "60000")
    monkeypatch.setenv("NOMETRIA_ENFORCEMENT_BUDGET_MS", "60000")
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_the_mutation_program_is_deterministic_under_a_fixed_seed(enforcing):
    """The part the seed actually controls: which probe is tried, mutated how, in
    what order. This holds regardless of what the enforcement pipeline's clock does."""
    from agentfox.core.models import RedTeamFinding

    def program(campaign):
        # Sorted, not insertion-ordered: finding ids are random, and what is being
        # pinned is *which* attempts happened, not the row order they landed in.
        rows = enforcing.query(RedTeamFinding).filter_by(campaign_id=campaign.id).all()
        return sorted(
            (r.probe, tuple(r.evidence_json["mutation_chain"]), r.evidence_json["attempt"])
            for r in rows
        )

    a = run_campaign(enforcing, "support-triage", adaptive=True, budget=4, seed=7, name="a")
    b = run_campaign(enforcing, "support-triage", adaptive=True, budget=4, seed=7, name="b")
    assert program(a) == program(b)


def test_results_are_deterministic_under_a_fixed_seed(enforcing, no_timing_flake):
    def fingerprint(campaign):
        adaptive = campaign.summary_json["adaptive"]
        return (
            campaign.summary_json["recall"],
            campaign.summary_json["precision"],
            adaptive["attempts_used"],
            sorted(adaptive["escaping_probes"]),
            sorted(adaptive["mutation_classes_that_worked"]),
            [(e["origin"], tuple(e["mutation_chain"]), e["verdict"]) for e in adaptive["escapes"]],
        )

    a = run_campaign(enforcing, "support-triage", adaptive=True, budget=4, seed=1337, name="a")
    b = run_campaign(enforcing, "support-triage", adaptive=True, budget=4, seed=1337, name="b")
    assert fingerprint(a) == fingerprint(b)


def test_a_different_seed_explores_a_different_path(enforcing):
    """The seed has to actually steer the search, otherwise "deterministic under a
    fixed seed" is true only because nothing varies at all."""
    a = run_campaign(enforcing, "support-triage", adaptive=True, budget=4, seed=1337, name="a")
    b = run_campaign(enforcing, "support-triage", adaptive=True, budget=4, seed=99, name="b")

    def chains(campaign):
        return {
            (e["origin"], tuple(e["mutation_chain"]))
            for e in campaign.summary_json["adaptive"]["escapes"]
        }

    chains_a, chains_b = chains(a), chains(b)
    assert chains_a != chains_b


def test_probe_rngs_are_independent_of_seed_list_order(enforcing):
    """Each probe's RNG is derived from its own key, so filtering or reordering the
    seed list cannot change the mutations another probe receives."""
    full = run_campaign(
        enforcing, "support-triage", adaptive=True, budget=4, include_deployment_probes=False
    )
    subset = run_campaign(
        enforcing,
        "support-triage",
        adaptive=True,
        budget=4,
        probes=["jailbreak.persona"],
        include_deployment_probes=False,
    )
    want = "jailbreak.persona"

    def chain_for(campaign):
        return [
            tuple(e["mutation_chain"])
            for e in campaign.summary_json["adaptive"]["escapes"]
            if e["origin"] == want
        ]

    chain_full, chain_subset = chain_for(full), chain_for(subset)
    assert chain_full == chain_subset


# ---------------------------------------------------------------------------
# Targeting the deployment, not the model
# ---------------------------------------------------------------------------


def test_deployment_profile_reads_the_real_configuration(enforcing):
    profile = deployment_profile(enforcing, "payments-ops")
    assert profile["known"] and profile["risk_tier"] == "high"
    granted = {g["tool_key"]: g for g in profile["grants"]}
    # The real seed grants, not a fixture: a <$1000 transfer ceiling, USD only.
    assert granted["payments.transfer"]["constraints"]["amount"] == {"lt": 1000}
    assert profile["tool_impacts"]["payments.transfer"] == "irreversible"
    assert "hr.score_candidate" in profile["ungranted_registered_tools"]
    assert {b["policy"] for b in profile["bound_policies"]} >= {"baseline", "tool-containment"}


def test_generated_probes_separate_ungranted_from_granted_with_bad_provenance(enforcing):
    """The distinction the task turns on: attempting a tool the agent genuinely lacks
    is a different test from attempting a granted tool with untrusted provenance.
    Both must be generated, and labelled apart."""
    probes = generate_deployment_probes(enforcing, "payments-ops")
    classes = {p.target_class for p in probes}
    assert "ungranted.registered" in classes
    assert "granted.untrusted_provenance" in classes
    assert "granted.constraint_breach" in classes
    assert "benign.within_limits" in classes

    ungranted = [p for p in probes if p.target_class == "ungranted.registered"]
    tainted = [p for p in probes if p.target_class == "granted.untrusted_provenance"]
    assert all(p.tool_key in enforcing_ungranted(enforcing, "payments-ops") for p in ungranted)
    assert all(p.provenance and set(p.provenance.values()) == {"retrieved"} for p in tainted)
    # The constraint breach is derived from the declared ceiling, not hardcoded.
    breach = next(p for p in probes if p.target_class == "granted.constraint_breach")
    assert breach.arguments["amount"] > 1000


def enforcing_ungranted(session, slug) -> set[str]:
    return set(deployment_profile(session, slug)["ungranted_registered_tools"])


def test_generated_probes_never_provision_anything(enforcing):
    """A campaign that creates a grant or a tool row is measuring itself."""
    from agentfox.core.models import Capability, Tool

    probes = generate_deployment_probes(enforcing, "support-triage")
    assert probes and all(p.provision is False for p in probes)

    before_tools = {t.key for t in enforcing.query(Tool).all()}
    before_caps = enforcing.query(Capability).count()
    run_campaign(
        enforcing, "support-triage", adaptive=True, budget=2, probes=[p.key for p in probes]
    )
    assert {t.key for t in enforcing.query(Tool).all()} == before_tools
    assert enforcing.query(Capability).count() == before_caps


def test_a_glob_grant_is_probed_for_overbreadth(enforcing):
    """`support-triage` holds `tickets.*`. A glob grant authorises every key added to
    that namespace after the grant was written, which is a configuration fact no
    static prompt list can discover."""
    probes = generate_deployment_probes(enforcing, "support-triage")
    glob = [p for p in probes if p.target_class == "granted.glob_overbreadth"]
    assert glob and glob[0].tool_key.startswith("tickets.")
    assert glob[0].tool_key not in {"tickets.create", "tickets.update"}


def test_deployment_probes_are_scored_separately_by_target_class(enforcing):
    campaign = run_campaign(enforcing, "payments-ops", adaptive=True, budget=3)
    by_target = campaign.summary_json["adaptive"]["by_target_class"]
    assert "static_suite" in by_target
    assert any(k.startswith("ungranted.") for k in by_target)
    assert sum(v["probes"] for v in by_target.values()) == campaign.summary_json["probes_run"]


def test_benign_controls_are_never_mutated(enforcing):
    """Mutating a probe that is supposed to be allowed produces something that is no
    longer a benign control — the precision number would quietly stop meaning
    anything."""
    from agentfox.core.models import RedTeamFinding

    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=4)
    benign_keys = {p["key"] for p in campaign.summary_json["probes"] if not p["expect_blocked"]}
    rows = enforcing.query(RedTeamFinding).filter_by(campaign_id=campaign.id).all()
    for row in rows:
        origin = row.evidence_json.get("origin") or row.probe
        if origin in benign_keys:
            assert row.evidence_json["mutation_chain"] == []


# ---------------------------------------------------------------------------
# Posture over time
# ---------------------------------------------------------------------------


def test_first_campaign_is_declared_a_baseline_not_a_result(enforcing):
    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=2)
    posture = campaign.summary_json["posture"]
    assert posture["direction"] == "no_baseline"
    assert posture["baseline"] is None
    assert "baseline" in campaign.summary_json["headline"]


def test_a_second_campaign_records_a_posture_delta(enforcing):
    first = run_campaign(enforcing, "support-triage", adaptive=True, budget=3, name="first")
    second = run_campaign(enforcing, "support-triage", adaptive=True, budget=3, name="second")

    posture = second.summary_json["posture"]
    assert posture["baseline"]["campaign_id"] == first.id
    # Same configuration, same seed, same budget -> the delta must be "unchanged".
    # Anything else means the comparison is picking up campaign-to-campaign noise
    # and would cry regression on every run.
    assert posture["direction"] == "unchanged"
    assert posture["new_escapes"] == [] and posture["resolved_escapes"] == []
    assert posture["escaping_now"] == posture["escaping_before"]
    assert "UNCHANGED" in second.summary_json["headline"]


CEILING_PROBE = ["capability.constraint_violation"]
CEILING_TOOL = "redteam.sim.issue_refund"


def _widen_the_refund_ceiling(session, constraints):
    """The regression this feature exists to catch, applied for real: somebody edits
    a capability grant and removes the argument ceiling on it. No policy changes, no
    detector changes — only the deployment's own configuration."""
    from agentfox.core.models import Capability

    cap = session.query(Capability).filter(Capability.tool_key == CEILING_TOOL).one()
    cap.constraints_json = constraints
    session.flush()


def test_posture_reports_weaker_when_the_configuration_regresses(enforcing):
    """The whole point of the feature. `capability.constraint_violation` asks for a
    $50,000 refund against a grant capped at $1,000. Between the two campaigns the
    cap is removed — a one-line configuration change that no static prompt suite
    would notice, because the *prompt* is identical in both runs."""
    from agentfox.core.models import Finding

    kwargs = dict(adaptive=True, budget=1, probes=CEILING_PROBE, include_deployment_probes=False)
    tight = run_campaign(enforcing, "support-triage", name="tight", **kwargs)
    assert tight.summary_json["adaptive"]["escaping_probes"] == []

    _widen_the_refund_ceiling(enforcing, {})
    widened = run_campaign(enforcing, "support-triage", name="widened", **kwargs)

    posture = widened.summary_json["posture"]
    assert posture["baseline"]["campaign_id"] == tight.id
    assert posture["direction"] == "weaker"
    assert posture["new_escapes"] == CEILING_PROBE
    assert "WEAKER" in widened.summary_json["headline"]
    assert enforcing.query(Finding).filter_by(type="redteam_posture_regression").all()


def test_posture_reports_stronger_when_the_configuration_improves(enforcing):
    kwargs = dict(adaptive=True, budget=1, probes=CEILING_PROBE, include_deployment_probes=False)
    run_campaign(enforcing, "support-triage", name="tight", **kwargs)
    _widen_the_refund_ceiling(enforcing, {})
    run_campaign(enforcing, "support-triage", name="widened", **kwargs)

    _widen_the_refund_ceiling(enforcing, {"amount": {"lt": 1000}})
    restored = run_campaign(enforcing, "support-triage", name="restored", **kwargs)
    posture = restored.summary_json["posture"]
    assert posture["direction"] == "stronger"
    assert posture["resolved_escapes"] == CEILING_PROBE


def test_an_observe_mode_binding_is_disclosed_next_to_the_counts(enforcing):
    """Found while building this and disclosed rather than inherited quietly: a probe
    is scored on `effective_verdict`, the counterfactual the bound policy asserts, so
    a policy demoted to observe mode moves no number in a campaign even though the
    deployment has stopped blocking anything. Every campaign therefore has to publish
    each bound policy's mode next to its blocked counts."""
    from agentfox.capabilities.evaluation.adaptive import NOT_ESTABLISHED
    from agentfox.platform.policy import set_mode

    set_mode(enforcing, "baseline", "observe")
    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=1)
    adaptive = campaign.summary_json["adaptive"]
    assert adaptive["bound_policy_modes"]["baseline"] == "observe"
    assert "baseline" in adaptive["observe_mode_policies"]
    assert any("observe" in item for item in NOT_ESTABLISHED)


def test_posture_compares_seed_probes_not_mutated_keys(enforcing):
    """Mutated probe keys embed the operator chain, so comparing those would report a
    difference whenever the search took a different but equally successful route."""
    run_campaign(enforcing, "support-triage", adaptive=True, budget=4, name="one")
    second = run_campaign(enforcing, "support-triage", adaptive=True, budget=4, name="two")
    for key in second.summary_json["posture"]["escaping_now"]:
        assert "+" not in key


def test_posture_ignores_an_incomparable_campaign_as_a_baseline(enforcing):
    """A campaign with a different budget or probe selection finds different things
    for reasons that have nothing to do with the deployment changing. Diffing against
    one would report a posture swing every run — the false signal that makes people
    stop reading a regression report."""
    run_campaign(enforcing, "support-triage", adaptive=True, budget=4, name="deep")
    shallow = run_campaign(enforcing, "support-triage", adaptive=True, budget=1, name="shallow")
    assert shallow.summary_json["posture"]["direction"] == "no_baseline"

    narrow = run_campaign(
        enforcing,
        "support-triage",
        adaptive=True,
        budget=4,
        probes=["jailbreak"],
        include_deployment_probes=False,
        name="narrow",
    )
    assert narrow.summary_json["posture"]["direction"] == "no_baseline"


def test_posture_ignores_static_campaigns_as_a_baseline(enforcing):
    """A static campaign is not a comparable measurement — different probe set,
    no mutation — so using one as the baseline would manufacture a regression."""
    run_campaign(enforcing, "support-triage", name="static-only")
    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=2)
    assert campaign.summary_json["posture"]["direction"] == "no_baseline"


# ---------------------------------------------------------------------------
# Honesty constraints
# ---------------------------------------------------------------------------


def test_every_adaptive_summary_carries_the_scope_statement(enforcing):
    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=2)
    summary = campaign.summary_json
    assert summary["what_this_measures"] == SCOPE_STATEMENT
    assert summary["adaptive"]["what_this_does_not_establish"] == NOT_ESTABLISHED


def test_the_scope_statement_refuses_the_robustness_reading(enforcing):
    lowered = SCOPE_STATEMENT.lower()
    assert "not adversarial robustness" in lowered
    assert "configuration regression testing" in lowered
    assert "do not cite it as robustness certification" in lowered
    assert any("adversarial robustness" in item.lower() for item in NOT_ESTABLISHED)


def test_headline_is_the_posture_sentence_not_a_pass_rate(enforcing):
    """ "92% blocked" is the number this feature must not lead with — a red-team pass
    rate goes up the weaker your probe set is."""
    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=2)
    headline = campaign.summary_json["headline"]
    assert headline == campaign.summary_json["posture"]["headline"]
    assert "%" not in headline


def test_escapes_record_the_exact_payload_that_worked(enforcing):
    """A reader who does not trust the aggregate has to be able to re-run the exact
    thing that got through."""
    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=4)
    escapes = campaign.summary_json["adaptive"]["escapes"]
    assert escapes
    for escape in escapes:
        assert escape["payload"] or escape["tool_key"]
        assert escape["mutation_chain"] or escape["attempt"] == 1


# ---------------------------------------------------------------------------
# Operator library invariants
# ---------------------------------------------------------------------------


def test_operator_library_is_well_formed():
    keys = [op.key for op in OPERATORS]
    assert len(keys) == len(set(keys))
    assert mutation_classes() == sorted({op.mutation_class for op in OPERATORS})
    for op in OPERATORS:
        assert op.kinds and set(op.kinds) <= {"content", "tool_call", "scenario"}
        assert op.description


def test_an_operator_is_never_applied_twice_to_the_same_probe(enforcing):
    from agentfox.core.models import RedTeamFinding

    campaign = run_campaign(enforcing, "support-triage", adaptive=True, budget=5)
    rows = enforcing.query(RedTeamFinding).filter_by(campaign_id=campaign.id).all()
    for row in rows:
        chain = row.evidence_json["mutation_chain"]
        assert len(chain) == len(set(chain))


def test_mutation_returns_none_at_an_honest_dead_end():
    """An empty payload has nothing any content operator can transform. The loop must
    say so rather than return the probe unchanged and burn the budget on repeats."""
    import random

    from agentfox.capabilities.evaluation.redteam import Probe

    empty = Probe("empty.probe", "prompt_injection", payload="")
    outcome = ProbeOutcome(probe=empty, blocked=True, verdict="block")
    assert next_mutation(empty, outcome, set(), random.Random("x")) is None
