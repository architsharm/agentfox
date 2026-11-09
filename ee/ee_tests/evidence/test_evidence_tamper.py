"""verify_chain.py against an attacker who edits the extracted package.

Each case is one the round-3 audit showed passing as CHAIN INTACT: an edited
decisions.json, a finding deleted from findings.json, an actor changed on an audit
entry, and a chain rewritten end to end with the verifier's own formula.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from agentfox_ee.evidence import package as evidence

from agentfox.core.models import AuditCheckpoint
from agentfox.platform.ledger import chain, finding_types
from agentfox.platform.ledger.findings import raise_finding

KEY = "test-key"  # conftest's AGENTFOX_AUDIT_SIGNING_KEY


@pytest.fixture
def pack(seeded, enforcer, tmp_path) -> Path:
    enforcer.run_completion(
        agent_slug="support-triage",
        messages=[{"role": "user", "content": "hello"}],
        model="echo-1",
    )
    for i in range(4):
        chain.append(
            seeded,
            "test.event",
            actor_type="user",
            actor_id="aisha@example.com",
            subject_type="thing",
            subject_id=f"s{i}",
            payload={"i": i},
        )
    finding_types.register(
        finding_types.FindingType("test_tamper", "Test", "low", "A fixture.", "tests")
    )
    for n in range(2):
        raise_finding(seeded, type="test_tamper", title=f"finding {n}", subject_id=f"agt_{n}")
    built = evidence.build(seeded, agents=["*"])
    out = tmp_path / "pkg"
    with zipfile.ZipFile(built.path) as zf:
        zf.extractall(out)
    return out


def run(pack: Path, key: str | None = None) -> subprocess.CompletedProcess:
    env = {
        k: v for k, v in os.environ.items() if not k.endswith(("_AUDIT_KEY", "_AUDIT_SIGNING_KEY"))
    }
    if key:
        env["AGENTFOX_AUDIT_SIGNING_KEY"] = key
    return subprocess.run(
        [sys.executable, "-I", "verify_chain.py"],
        cwd=pack,
        capture_output=True,
        text=True,
        env=env,
    )


def load(pack: Path, name: str):
    return json.loads((pack / name).read_text())


def dump(pack: Path, name: str, value) -> None:
    (pack / name).write_text(json.dumps(value, indent=2))


def reseal_manifest(pack: Path) -> None:
    """What a forger without the key can do: recompute every hash in the manifest."""
    manifest = load(pack, "manifest.json")
    for name in manifest["files"]:
        body = (pack / name).read_bytes()
        manifest["files"][name] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    dump(pack, "manifest.json", manifest)


def test_an_untouched_package_verifies_with_and_without_the_key(pack):
    keyless = run(pack)
    assert keyless.returncode == 0, keyless.stdout
    assert "CHAIN INTACT" in keyless.stdout
    assert "not that it is unaltered" in keyless.stdout
    keyed = run(pack, KEY)
    assert keyed.returncode == 0, keyed.stdout
    assert "manifest signature" in keyed.stdout


def test_an_edited_decision_is_caught(pack):
    decisions = load(pack, "decisions.json")
    assert decisions
    decisions[0]["verdict"] = "block" if decisions[0]["verdict"] != "block" else "allow"
    dump(pack, "decisions.json", decisions)
    out = run(pack)
    assert out.returncode == 1
    assert "file_mismatch: decisions.json" in out.stdout


def test_a_deleted_finding_is_caught(pack):
    findings = load(pack, "findings.json")
    dump(pack, "findings.json", findings[1:])
    out = run(pack)
    assert out.returncode == 1
    assert "file_mismatch: findings.json" in out.stdout


def test_a_deleted_file_and_an_added_file_are_caught(pack):
    (pack / "findings.json").unlink()
    (pack / "extra.json").write_text("{}")
    out = run(pack)
    assert out.returncode == 1
    assert "file_missing: findings.json" in out.stdout
    assert "file_unlisted: extra.json" in out.stdout


def test_a_resealed_manifest_passes_keyless_but_not_with_the_key(pack):
    decisions = load(pack, "decisions.json")
    decisions[0]["verdict"] = "block" if decisions[0]["verdict"] != "block" else "allow"
    dump(pack, "decisions.json", decisions)
    reseal_manifest(pack)
    # Without the key the package is only consistent, and the output says so.
    assert run(pack).returncode == 0
    keyed = run(pack, KEY)
    assert keyed.returncode == 1
    assert "manifest_signature" in keyed.stdout


def test_an_actor_change_is_caught(pack):
    entries = load(pack, "audit_entries.json")
    target = next(e for e in entries if e["actor_id"] == "aisha@example.com")
    target["actor_id"] = "someone-else@example.com"
    dump(pack, "audit_entries.json", entries)
    reseal_manifest(pack)
    out = run(pack)
    assert out.returncode == 1
    assert "digest_mismatch" in out.stdout


def test_a_subject_change_is_caught(pack):
    entries = load(pack, "audit_entries.json")
    target = next(e for e in entries if e["subject_id"] == "s1")
    target["subject_id"] = "s9"
    dump(pack, "audit_entries.json", entries)
    reseal_manifest(pack)
    out = run(pack)
    assert out.returncode == 1
    assert "digest_mismatch" in out.stdout


def _rewrite_chain(entries: list[dict]) -> None:
    """Recompute every digest from GENESIS with the verifier's own v2 formula."""
    prev = chain.GENESIS
    for row in entries:
        row["prev_digest"] = prev
        row["payload_digest"] = chain.compute_payload_digest(row.get("payload") or {})
        row["subject_digest"] = chain.compute_subject_digest(row.get("subject_id"))
        row["digest_version"] = 2
        row["digest"] = chain.compute_digest_v2(
            row["seq"],
            dt.datetime.fromisoformat(row["occurred_at"]),
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            action=row["action"],
            subject_type=row["subject_type"],
            subject_digest=row["subject_digest"],
            payload_digest=row["payload_digest"],
            prev_digest=prev,
        )
        prev = row["digest"]


def test_a_rewritten_chain_is_caught_with_the_key(pack):
    """A keyless forger drops an entry and recomputes the whole chain and manifest."""
    entries = load(pack, "audit_entries.json")
    del entries[2]
    for seq, row in enumerate(entries, start=1):
        row["seq"] = seq
    _rewrite_chain(entries)
    dump(pack, "audit_entries.json", entries)
    reseal_manifest(pack)

    assert run(pack).returncode == 0  # consistent, as the keyless note warns
    keyed = run(pack, KEY)
    assert keyed.returncode == 1
    assert "manifest_signature" in keyed.stdout
    assert "checkpoint_digest" in keyed.stdout


def test_a_package_always_carries_a_checkpoint_on_its_newest_entry(seeded, monkeypatch):
    """UI-built packages had 0 checkpoints when fewer than 100 entries had been written."""
    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("AGENTFOX_AUDIT_CHECKPOINT_INTERVAL", "1000")
    reset_settings_cache()
    for i in range(3):
        chain.append(seeded, "test.event", payload={"i": i})
    assert seeded.query(AuditCheckpoint).count() == 0

    built = evidence.build(seeded, agents=["*"])
    with zipfile.ZipFile(built.path) as zf:
        entries = json.loads(zf.read("audit_entries.json"))
        checkpoints = json.loads(zf.read("audit_checkpoints.json"))
    assert built.manifest_json["counts"]["checkpoints"] >= 1
    assert checkpoints[-1]["seq"] == entries[-1]["seq"]
    assert checkpoints[-1]["digest"] == entries[-1]["digest"]
