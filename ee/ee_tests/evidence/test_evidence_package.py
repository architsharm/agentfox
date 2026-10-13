"""Pillar 5 — the tamper-evident chain and evidence packages.

These are the tests that decide whether the compliance claims mean anything. If the
chain has a bug, every control status and every evidence package built on it is void
(Appendix E.2.3), so each tamper mode is asserted individually.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import zipfile

import pytest
from agentfox_ee.evidence import package as evidence

from agentfox.core.models import AuditEntry
from agentfox.platform.ledger import chain
from agentfox.platform.ledger.chain import entry_to_row


@pytest.fixture
def chained(session):
    for i in range(12):
        chain.append(
            session,
            "test.event",
            subject_type="thing",
            subject_id=f"s{i}",
            payload={"i": i, "note": f"entry {i}"},
        )
    return session


def rows(session) -> list[dict]:
    return [entry_to_row(e) for e in session.query(AuditEntry).order_by(AuditEntry.seq)]


# ---------------------------------------------------------------------------
# Chain integrity (P5-2, NFR-5)
# ---------------------------------------------------------------------------


def test_evidence_package_contents(seeded, tmp_path):
    chain.append(seeded, "test.event", payload={"a": 1})
    package = evidence.build(seeded, agents=["*"], requested_by="aisha@example.com")

    with zipfile.ZipFile(package.path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        readme = zf.read("README.txt").decode()

    assert {
        "manifest.json",
        "audit_entries.json",
        "traces.json",
        "decisions.json",
        "policy_versions.json",
        "control_status.json",
        "framework_mappings.json",
        "chain_verification.json",
        "verify_chain.py",
        "README.txt",
    } <= names
    assert manifest["generated_by"] == "aisha@example.com"
    assert manifest["chain_verification"]["valid"] is True
    assert "verify_chain.py" in readme


def test_draft_mappings_included_with_chip(seeded):
    """Unreviewed regulatory mappings ship as evidence, chip-labeled draft (Appendix B §B.6)."""
    package = evidence.build(seeded, agents=["*"], requested_by="dana@example.com")
    with zipfile.ZipFile(package.path) as zf:
        mappings = json.loads(zf.read("framework_mappings.json"))
    assert mappings, "seeded catalog is all draft; drafts should still be exported"
    assert all(m["review_status"] == "draft" for m in mappings)
    assert all(m["chip"] == "DRAFT — UNVERIFIED / NOT LEGAL ADVICE" for m in mappings)
    assert package.manifest_json["counts"]["draft_mappings_included"] == len(mappings)


def test_reviewed_mappings_are_included(seeded):
    from agentfox_ee.compliance.frameworks import review_mapping

    review_mapping(seeded, "NOM-RTG-01", "eu-ai-act", "dana@example.com")
    package = evidence.build(seeded, agents=["*"], requested_by="dana@example.com")
    with zipfile.ZipFile(package.path) as zf:
        mappings = json.loads(zf.read("framework_mappings.json"))
    reviewed = [m for m in mappings if m["control_key"] == "NOM-RTG-01"]
    assert reviewed and reviewed[0]["chip"] == "REVIEWED"


def test_manifest_digests_match_files(seeded):
    import hashlib

    package = evidence.build(seeded, agents=["*"])
    with zipfile.ZipFile(package.path) as zf:
        for name, meta in package.manifest_json["files"].items():
            body = zf.read(name)
            assert hashlib.sha256(body).hexdigest() == meta["sha256"], name


def test_shipped_verifier_runs_standalone(seeded, tmp_path):
    """The central claim: an auditor can verify without trusting or calling us."""
    for i in range(6):
        chain.append(seeded, "test.event", subject_id=f"s{i}", payload={"i": i})
    package = evidence.build(seeded, agents=["*"])
    extract = tmp_path / "pkg"
    with zipfile.ZipFile(package.path) as zf:
        zf.extractall(extract)

    ok = subprocess.run(
        [sys.executable, "verify_chain.py"], cwd=extract, capture_output=True, text=True
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "CHAIN INTACT" in ok.stdout

    entries = json.loads((extract / "audit_entries.json").read_text())
    entries[1]["payload"]["tampered"] = True
    (extract / "audit_entries.json").write_text(json.dumps(entries))

    bad = subprocess.run(
        [sys.executable, "verify_chain.py"], cwd=extract, capture_output=True, text=True
    )
    assert bad.returncode == 1
    assert "CHAIN INVALID" in bad.stdout
    assert "payload_mismatch" in bad.stdout


def test_exporting_evidence_is_itself_audited(seeded):
    """Who produced the evidence is audit-relevant (Appendix C §5)."""
    before = seeded.query(AuditEntry).count()
    evidence.build(seeded, agents=["*"], requested_by="aisha@example.com")
    after = seeded.query(AuditEntry).filter_by(action="evidence.exported").count()
    assert after == 1
    assert seeded.query(AuditEntry).count() > before


def test_evidence_scope_is_honoured(seeded, enforcer):
    enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hello"}],
        model="echo-1",
    )
    package = evidence.build(
        seeded,
        agents=["support-triage"],
        period_from=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
    )
    with zipfile.ZipFile(package.path) as zf:
        agents = json.loads(zf.read("agents.json"))
    assert {a["slug"] for a in agents} == {"support-triage"}


@pytest.mark.parametrize(
    "variable",
    ["AGENTFOX_AUDIT_KEY", "AGENTFOX_AUDIT_KEY", "AGENTFOX_AUDIT_SIGNING_KEY"],
)
def test_shipped_verifier_reads_the_key_under_either_prefix(seeded, tmp_path, variable):
    """AGENTFOX_ is the name; AGENTFOX_ keeps working for anyone who wrote it down."""
    import os

    for i in range(3):
        chain.append(seeded, "test.event", subject_id=f"s{i}", payload={"i": i})
    chain.checkpoint_now(seeded)
    package = evidence.build(seeded, agents=["*"])
    extract = tmp_path / "pkg"
    with zipfile.ZipFile(package.path) as zf:
        zf.extractall(extract)

    base = {
        k: v for k, v in os.environ.items() if not k.endswith(("_AUDIT_KEY", "_AUDIT_SIGNING_KEY"))
    }

    def run(key: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "verify_chain.py"],
            cwd=extract,
            capture_output=True,
            text=True,
            env={**base, variable: key},
        )

    good = run("test-key")  # conftest's signing key
    assert good.returncode == 0, good.stdout + good.stderr
    assert "not set" not in good.stdout
    bad = run("wrong-key")
    assert bad.returncode == 1
    assert "checkpoint_signature" in bad.stdout


def test_a_scoped_package_leaves_other_agents_out_of_every_file(seeded, enforcer, tmp_path):
    """#66: agent scope filtered agents and traces only; findings, approvals, eval runs
    and audit entries for every other agent shipped in a package scoped to one."""
    from agentfox.core.models import Agent, ApprovalRequest, EvalRun
    from agentfox.platform.ledger import finding_types
    from agentfox.platform.ledger.findings import raise_finding

    agents = {a.slug: a for a in seeded.query(Agent).all()}
    other = next(slug for slug in agents if slug != "support-triage")
    for slug in ("support-triage", other):
        finding_types.register(
            finding_types.FindingType(f"test_{slug}", f"Test {slug}", "low", "A fixture.", "tests")
        )
        enforcer.run_completion(
            agent_slug=slug, messages=[{"role": "user", "content": "hello"}], model="echo-1"
        )
        raise_finding(
            seeded,
            type=f"test_{slug}",
            severity="low",
            title=f"finding about {slug}",
            subject_type="agent",
            subject_id=agents[slug].id,
        )
        seeded.add(ApprovalRequest(agent_id=agents[slug].id, tool_key=f"{slug}.tool"))
        seeded.add(EvalRun(suite_id="s", target_json={"agent": slug}))
        chain.append(
            seeded,
            "test.agent_event",
            subject_type="agent",
            subject_id=agents[slug].id,
            payload={"note": f"about {slug}"},
        )
    seeded.flush()

    package = evidence.build(
        seeded,
        agents=["support-triage"],
        period_from=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
    )
    extract = tmp_path / "pkg"
    with zipfile.ZipFile(package.path) as zf:
        zf.extractall(extract)

    def load(name):
        return json.loads((extract / name).read_text())

    triage_id = agents["support-triage"].id
    assert {f["title"] for f in load("findings.json") if f["type"].startswith("test_")} == {
        "finding about support-triage"
    }
    assert {a["tool"] for a in load("approvals.json")} == {"support-triage.tool"}
    assert {r["target"]["agent"] for r in load("eval_runs.json")} == {"support-triage"}
    decisions = load("decisions.json")
    assert decisions
    traces = {t["trace"]["id"] if "trace" in t else t.get("id") for t in load("traces.json")}
    assert all(d["trace_id"] in traces for d in decisions)

    entries = load("audit_entries.json")
    raw = (extract / "audit_entries.json").read_text()
    assert f"about {other}" not in raw
    assert "about support-triage" in raw
    withheld = [e for e in entries if e.get("payload_withheld")]
    assert withheld and all(e["payload"] is None for e in withheld)
    assert any(e["subject_id"] == triage_id for e in entries)

    # The chain still verifies with other agents' payloads withheld.
    ok = subprocess.run(
        [sys.executable, "verify_chain.py"], cwd=extract, capture_output=True, text=True
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr

    # And the withheld flag cannot be used to hide an edited payload.
    withheld[0]["payload"] = {"forged": True}
    (extract / "audit_entries.json").write_text(json.dumps(entries))
    bad = subprocess.run(
        [sys.executable, "verify_chain.py"], cwd=extract, capture_output=True, text=True
    )
    assert bad.returncode == 1
