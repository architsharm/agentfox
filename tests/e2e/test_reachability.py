"""The protective controls, reachable without writing code.

The audit's usability finding was the business blocker: *what is trivial is what
observes, and what is expert-only is what protects*. Three complete engines were
unreachable — answerability was REST-only, provenance was Python-only with no HTTP
surface at all, and escalation needed the host application to push conversation turns
that nothing was pushing.

A control nobody can switch on is not a control. These tests check that each of them
can now be reached the same way `agentfox check` is: one command, no client library,
no reading the PRD first.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from agentfox.cli.main import app
from tests.conftest import as_user

runner = CliRunner()


@pytest.fixture
def ready(isolated_db):
    """Seeded and committed — the CLI opens its own session, so an uncommitted fixture
    would leave it looking at an empty database."""
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        seed(session)
    yield


def flat(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# P8 — provenance had no interface at all
# ---------------------------------------------------------------------------


def test_a_source_can_be_tiered_from_the_command_line(isolated_db):
    result = runner.invoke(
        app,
        ["declare", "source", "price-book", "--tier", "system_of_record", "--owner", "fin@x.test"],
    )
    assert result.exit_code == 0, result.output
    listed = runner.invoke(app, ["declare", "list", "sources", "--json"])
    rows = json.loads(listed.output)
    assert rows[0]["key"] == "price-book"
    assert rows[0]["tier"] == "system_of_record"


def test_an_unknown_tier_is_refused_with_the_valid_ones(isolated_db):
    result = runner.invoke(app, ["declare", "source", "x", "--tier", "trustworthy"])
    assert result.exit_code == 1
    assert "system_of_record" in flat(result.output)


def test_a_corpus_can_be_imported_in_one_go(isolated_db, tmp_path):
    """Nobody classifies four hundred sources one command at a time, and making them
    try is how the tiering never happens."""
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            [
                {"key": "price-book", "tier": "system_of_record", "owner": "fin@x.test"},
                {"key": "wiki", "tier": "approved"},
                {"key": "notes", "tier": "unverified"},
            ]
        )
    )
    result = runner.invoke(app, ["declare", "import-sources", str(manifest)])
    assert result.exit_code == 0
    assert "3 source(s)" in flat(result.output)


def test_an_sla_without_an_update_time_explains_why_it_reads_stale(isolated_db):
    """Treating unknown age as a breach is deliberate. Not saying so leaves the
    operator wondering why a source they just added is already stale."""
    result = runner.invoke(
        app, ["declare", "source", "gl", "--tier", "approved", "--sla-hours", "24"]
    )
    assert "no update time is recorded" in flat(result.output)


def test_the_empty_state_says_what_it_means(isolated_db):
    result = runner.invoke(app, ["declare", "list", "sources"])
    assert "No sources registered" in flat(result.output)
    assert "authoritative answer from a confident one" in flat(result.output)


def test_sources_are_reachable_over_http(client):
    """P8 shipped with zero API routes — the only way in was to import our package."""
    headers = as_user("priya@example.com")
    before = client.get("/api/sources", headers=headers).json()
    before_health = client.get("/api/sources/health", headers=headers).json()

    created = client.put(
        "/api/sources",
        json={"key": "price-book", "tier": "system_of_record", "owner": "fin@x.test"},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    listing = client.get("/api/sources", headers=headers).json()
    assert listing["counts"]["system_of_record"] == before["counts"]["system_of_record"] + 1
    assert any(s["key"] == "price-book" for s in listing["sources"])

    health = client.get("/api/sources/health", headers=headers).json()
    assert health["registered"] == before_health["registered"] + 1


def test_retiring_a_source_deprecates_rather_than_deletes(client):
    """A deleted source silently becomes *unverified* again — the default for anything
    unregistered — where a deprecated one keeps raising a finding. Losing that signal
    is the wrong outcome for a source retired because it was wrong."""
    headers = as_user("priya@example.com")
    client.put("/api/sources", json={"key": "wiki-2019", "tier": "approved"}, headers=headers)
    response = client.delete("/api/sources/wiki-2019", headers=headers)
    assert response.status_code == 200
    assert response.json()["deprecated"] is True

    listing = client.get("/api/sources", headers=headers).json()
    wiki = next(s for s in listing["sources"] if s["key"] == "wiki-2019")
    assert wiki["deprecated"] is True


def test_provenance_can_be_dry_run_before_it_is_wired_in(client):
    headers = as_user("priya@example.com")
    client.put(
        "/api/sources",
        json={"key": "wiki", "tier": "approved", "deprecated": True},
        headers=headers,
    )
    body = client.post(
        "/api/sources/assess",
        json={
            "answer": "The limit is 500 [wiki].",
            "chunks": [{"source": "wiki", "text": "the limit is 500"}],
        },
        headers=headers,
    ).json()
    assert body["clean"] is False
    assert body["breaches"][0]["kind"] == "deprecated_source"


# ---------------------------------------------------------------------------
# P7 — answerability was REST-only
# ---------------------------------------------------------------------------


def test_a_knowledge_boundary_can_be_declared_from_the_command_line(ready):
    result = runner.invoke(
        app,
        [
            "declare",
            "boundary",
            "support-triage",
            "--systems",
            "CRM",
            "--coverage-months",
            "24",
            "--answerable",
            "fact,aggregate",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "boundary declared" in flat(result.output)
    assert "observe mode" in flat(result.output)


def test_an_unknown_question_type_lists_the_valid_ones(ready):
    result = runner.invoke(app, ["declare", "boundary", "support-triage", "--answerable", "vibes"])
    assert result.exit_code == 1
    assert "prediction" in flat(result.output)


def test_a_question_can_be_dry_run_against_the_boundary(ready):
    runner.invoke(
        app, ["declare", "boundary", "support-triage", "--systems", "CRM", "--answerable", "fact"]
    )
    refused = runner.invoke(
        app, ["test", "boundary", "support-triage", "what will revenue be next year?"]
    )
    assert "would abstain" in flat(refused.output)
    allowed = runner.invoke(
        app, ["test", "boundary", "support-triage", "what was the order status?"]
    )
    assert "answerable" in flat(allowed.output)


def test_checking_without_a_boundary_says_so_rather_than_passing_silently(ready):
    # support-triage carries a real seeded boundary (NOM-RTG-11); hr-screening
    # deliberately doesn't, so it's the one that still exercises this path.
    result = runner.invoke(app, ["test", "boundary", "hr-screening", "anything"])
    assert "no boundary declared" in flat(result.output)


# ---------------------------------------------------------------------------
# P11 — escalation needed the host application to push turns
# ---------------------------------------------------------------------------


def test_an_escalation_policy_can_be_set_from_the_command_line(ready):
    result = runner.invoke(
        app, ["declare", "escalation", "--agent", "support-triage", "--turn-depth", "4"]
    )
    assert result.exit_code == 0, result.output
    assert "escalation policy" in flat(result.output)


def test_the_missed_escalation_scan_is_read_only_by_default(ready):
    from agentfox.containment.escalation import record_turn
    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding

    with session_scope() as session:
        record_turn(
            session,
            session_id="s1",
            user_text="I need to speak to a human",
            agent_text="I can help here.",
        )

    result = runner.invoke(app, ["report", "escalations"])
    assert "1 missed" in flat(result.output)
    assert "--apply" in flat(result.output)

    with session_scope() as session:
        assert session.query(Finding).filter_by(type="missed_escalation").count() == 0

    runner.invoke(app, ["report", "escalations", "--apply"])
    with session_scope() as session:
        assert session.query(Finding).filter_by(type="missed_escalation").count() == 1


# ---------------------------------------------------------------------------
# The one-liner now feeds escalation
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_openai():
    import sys
    import types

    saved = {k: sys.modules.get(k) for k in list(sys.modules) if k.startswith("openai")}
    openai = types.ModuleType("openai")
    openai.__version__ = "1.99.0"
    resources = types.ModuleType("openai.resources")
    chat = types.ModuleType("openai.resources.chat")
    completions = types.ModuleType("openai.resources.chat.completions")

    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    class Completions:
        def create(self, **kwargs):
            return _Response("I don't have access to that information.")

    completions.Completions = Completions
    chat.completions = completions
    resources.chat = chat
    openai.resources = resources
    sys.modules.update(
        {
            "openai": openai,
            "openai.resources": resources,
            "openai.resources.chat": chat,
            "openai.resources.chat.completions": completions,
        }
    )
    yield Completions
    from agentfox.runtime.autoguard import off

    off()
    for key in [k for k in list(sys.modules) if k.startswith("openai")]:
        del sys.modules[key]
    for key, value in saved.items():
        if value is not None:
            sys.modules[key] = value


def test_the_one_liner_captures_conversation_turns(isolated_db, fake_openai):
    """Escalation governance was complete and inert for anyone using `auto()`: the
    detector reads recorded turns, and nothing was recording them. The largest failure
    family was covered in code and uncovered in practice."""
    from agentfox.containment.escalation import detect_missed_escalation
    from agentfox.core.db import session_scope
    from agentfox.core.models import ConversationTurn
    from agentfox.fixtures.seed import seed
    from agentfox.runtime.autoguard import auto

    with session_scope() as session:
        seed(session)

    auto(agent="support-triage", session_id="conv-1", quiet=True)
    for question in ("where is my refund?", "can you check again?", "I need a human"):
        fake_openai().create(model="gpt-4o", messages=[{"role": "user", "content": question}])

    with session_scope() as session:
        # filtered to this test's own session — the seed demo carries a real,
        # already-escalated conversation of its own (seed-refund-dispute-1)
        assert session.query(ConversationTurn).filter_by(session_id="conv-1").count() == 3
        result = detect_missed_escalation(
            session, raise_findings=False, agent_slug="support-triage"
        )
    assert result["qualified"] == 1
    assert len(result["missed"]) == 1


def test_turns_group_into_one_conversation(isolated_db, fake_openai):
    """Without a session id every exchange looks like a separate single-turn
    conversation, and turn-depth conditions can never fire."""
    from agentfox.core.db import session_scope
    from agentfox.core.models import ConversationTurn
    from agentfox.fixtures.seed import seed
    from agentfox.runtime.autoguard import auto

    with session_scope() as session:
        seed(session)

    auto(agent="support-triage", session_id="conv-2", quiet=True)
    for _ in range(3):
        fake_openai().create(model="gpt-4o", messages=[{"role": "user", "content": "hello"}])

    with session_scope() as session:
        turns = session.query(ConversationTurn).filter_by(session_id="conv-2").all()
    # scoped to conv-2 — the seed demo carries a real conversation of its own
    # (seed-refund-dispute-1) that would otherwise mix into these assertions
    assert {t.session_id for t in turns} == {"conv-2"}
    assert sorted(t.turn_index for t in turns) == [0, 1, 2]


def test_turn_capture_never_breaks_the_call(isolated_db, fake_openai, monkeypatch):
    """Observability must not be able to fail the path it is describing."""
    import agentfox.runtime.autoguard as autoguard
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed
    from agentfox.runtime.autoguard import auto

    with session_scope() as session:
        seed(session)
    auto(agent="support-triage", quiet=True)

    def explode(*args, **kwargs):
        raise RuntimeError("turn store unavailable")

    monkeypatch.setattr(autoguard, "_record_turn", explode)
    response = fake_openai().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert response.choices[0].message.content


# ---------------------------------------------------------------------------
# Every protective control now has a way in
# ---------------------------------------------------------------------------


def test_each_protective_control_has_a_command(isolated_db):
    """The audit counted two of fifteen pillars usable without expert configuration."""
    # The controls are declared under `declare` and operated under `admin` since the
    # CLI consolidation; the old top-level groups still run, hidden.
    help_text = flat(runner.invoke(app, ["--help"]).output)
    for verb in ("declare", "permit", "admin"):
        assert verb in help_text, verb
    declare_help = flat(runner.invoke(app, ["declare", "--help"]).output)
    for verb in ("boundary", "source", "escalation", "principal"):
        assert verb in declare_help, verb
    assert "auth" in flat(runner.invoke(app, ["admin", "--help"]).output)


def test_the_duplicate_id_lint_actually_fires(isolated_db):
    """Regression: this lint code passed `level` positionally into `message` *and* a
    `message=` keyword, so it raised TypeError every time it fired.

    Nothing caught it because no test ever wrote a policy with a duplicated rule id —
    the one situation the check exists for. Found by the coverage probe.
    """
    from agentfox.platform.policy import PolicyDocument, PolicyLayer, lint_policy

    document = PolicyDocument.model_validate(
        {
            "key": "probe",
            "name": "probe",
            "version": 1,
            "rules": [
                {"id": "catch-all", "effect": "block", "when": {}},
                {"id": "catch-all", "effect": "allow", "when": {}},
            ],
        }
    )
    findings = lint_policy([PolicyLayer(document=document)])
    codes = {finding.code for finding in findings}
    assert "duplicate-id" in codes
    duplicate = next(f for f in findings if f.code == "duplicate-id")
    assert "silently wins" in duplicate.message
