"""Four defects found by running every command of the published package by hand.

None of these are crashes, which is why nothing caught them: each command exits 0
and prints something plausible. What was wrong was the *content* — copy a customer
reads, a workflow with a missing link in the middle, a green result that could not
have been red, and a typo that told you nothing.
"""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.cli.main import app

runner = CliRunner()


def flat(output: str) -> str:
    return " ".join(output.split())


def _seed() -> dict:
    from agentfox.db import session_scope
    from agentfox.seed import seed

    with session_scope() as session:
        return seed(session)


# ---------------------------------------------------------------------------
# 1. the abstention a customer reads
# ---------------------------------------------------------------------------


def test_the_refusal_does_not_say_a_opinion_question():
    """This string is shown to the end user of someone else's product.

    "That's a opinion question" is the sort of slip that makes the whole control
    look automated, which is the opposite of what an abstention needs to convey.
    """
    from agentfox.answerability import classify_answerability
    from agentfox.models import KnowledgeBoundary

    boundary = KnowledgeBoundary(
        systems_of_record=["zendesk"],
        answerable_types=["fact", "aggregate", "procedure"],
        mode="observe",
    )
    verdict = classify_answerability("should I sue my employer?", boundary)

    assert verdict.question_type == "opinion"
    assert "an opinion question" in verdict.response
    assert "a opinion" not in verdict.response


def test_the_refusal_lists_answerable_types_as_a_sentence():
    """"fact or aggregate or procedure" reads as a machine listing enum members."""
    from agentfox.answerability import classify_answerability
    from agentfox.models import KnowledgeBoundary

    boundary = KnowledgeBoundary(
        systems_of_record=["zendesk"],
        answerable_types=["fact", "aggregate", "procedure"],
        mode="observe",
    )
    response = classify_answerability("should I sue my employer?", boundary).response
    assert "fact, aggregate or procedure" in response


def test_a_single_answerable_type_is_not_given_a_comma():
    from agentfox.answerability import classify_answerability
    from agentfox.models import KnowledgeBoundary

    boundary = KnowledgeBoundary(
        systems_of_record=["zendesk"], answerable_types=["fact"], mode="observe"
    )
    response = classify_answerability("should I sue my employer?", boundary).response
    assert "answer fact questions" in response


# ---------------------------------------------------------------------------
# 2. run -> baseline -> gate had no middle
# ---------------------------------------------------------------------------


def test_eval_run_prints_the_run_id_that_eval_baseline_requires():
    """`eval baseline` takes a run id, and nothing in the CLI ever printed one.

    The documented workflow was unusable without opening the database.
    """
    _seed()
    result = runner.invoke(app, ["eval", "run", "support-quality"])
    assert result.exit_code == 0, result.output

    from sqlalchemy import select

    from agentfox.db import session_scope
    from agentfox.models import EvalRun

    with session_scope() as session:
        run_id = session.scalars(select(EvalRun.id)).first()

    assert run_id and run_id in flat(result.output)
    # And it says what to do with it, rather than leaving an opaque id on screen.
    assert "eval baseline" in flat(result.output)


# ---------------------------------------------------------------------------
# 3. a gate that could not have failed said GATE PASS and nothing else
# ---------------------------------------------------------------------------


def test_a_gate_with_no_baseline_and_no_floor_says_it_could_not_have_failed():
    """Green here means "nothing was compared", not "no regression".

    Left unsaid, the first CI run prints GATE PASS and the team believes the
    build is protected when the gate is empty — the same shape of failure as a
    deployment announcing enforce mode while enforcing nothing.
    """
    _seed()
    result = runner.invoke(app, ["eval", "gate", "support-quality"])
    output = flat(result.output)

    assert result.exit_code == 0
    assert "GATE PASS" in output
    assert "nothing to fail against" in output
    assert "--min-pass-rate" in output


def test_an_armed_gate_does_not_carry_the_warning():
    """The notice must be about *this* gate, not printed on every pass."""
    _seed()
    runner.invoke(app, ["eval", "run", "support-quality"])
    result = runner.invoke(
        app, ["eval", "gate", "support-quality", "--min-pass-rate", "0.0"]
    )
    assert result.exit_code == 0
    assert "nothing to fail against" not in flat(result.output)


# ---------------------------------------------------------------------------
# 4. required names nothing would tell you
# ---------------------------------------------------------------------------


def test_an_unknown_suite_names_the_suites_that_exist():
    _seed()
    result = runner.invoke(app, ["eval", "run", "no-such-suite"])
    assert result.exit_code == 1
    assert "support-quality" in flat(result.output)


def test_eval_suites_lists_them_without_a_failed_command_first():
    _seed()
    result = runner.invoke(app, ["eval", "suites"])
    assert result.exit_code == 0, result.output
    assert "support-quality" in flat(result.output)


def test_an_unknown_agent_names_the_agents_that_exist():
    """`capability` did this and `agents`/`boundary`/`escalation` did not, so
    whether a typo told you the answer depended on which command you typed."""
    _seed()
    for argv in (
        ["agents", "quarantine", "no-such-agent"],
        ["boundary", "check", "no-such-agent", "what is our refund policy?"],
    ):
        result = runner.invoke(app, argv)
        assert result.exit_code == 1, argv
        assert "support-triage" in flat(result.output), argv


def test_an_empty_deployment_points_at_seed_rather_than_an_empty_list():
    result = runner.invoke(app, ["agents", "quarantine", "anything"])
    assert result.exit_code == 1
    assert "no agents registered yet" in flat(result.output)


# ---------------------------------------------------------------------------
# 5. the one list command with no empty state
# ---------------------------------------------------------------------------


def test_proposals_list_says_something_when_there_are_none():
    """It printed a column header and nothing under it, which reads as broken.

    `findings`, `sources list`, `tools list` and `capability list` all say what
    is missing and how to get some; this one did not.
    """
    result = runner.invoke(app, ["proposals", "list"])
    assert result.exit_code == 0
    output = flat(result.output)
    assert "no proposals" in output
    assert "from-labels" in output


def test_an_empty_filter_result_is_not_reported_as_an_empty_deployment():
    """"there are none" and "none matched what you asked for" are different."""
    result = runner.invoke(app, ["proposals", "list", "--status", "approved"])
    assert result.exit_code == 0
    assert "no proposals match that filter" in flat(result.output)
