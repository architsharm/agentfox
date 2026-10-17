"""The finding-type registry: every type the product raises is registered.

Two nets. The static one below reads the source for every literal a finding type can
come from. The dynamic one is `tests/conftest.py` setting strict mode, so any finding
the suite raises with an unregistered type fails the test that raised it.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from agentfox.platform.ledger import finding_types
from agentfox.platform.ledger.findings import raise_finding

SRC = Path(__file__).resolve().parents[3] / "src" / "agentfox"

#: Modules whose ``{"type": ...}`` dict literals become findings: the content checks'
#: evidence issues, the MCP server scan's issues.
ISSUE_MODULES = (
    "capabilities/grounding/checks.py",
    "capabilities/containment/checks.py",
    "capabilities/detection/checks.py",
    "platform/registry/service.py",
)


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _types_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    rel = path.relative_to(SRC).as_posix()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name and name.lstrip("_") == "raise_finding":
                for keyword in node.keywords:
                    if keyword.arg == "type" and (value := _literal(keyword.value)):
                        found.add(value)
            if name == "_issue" and rel == "capabilities/discovery/skills.py" and node.args:
                if value := _literal(node.args[0]):
                    found.add(value)
        if isinstance(node, ast.Assign):
            targets = [getattr(t, "id", None) for t in node.targets]
            if "FINDING_TYPE" in targets and (value := _literal(node.value)):
                found.add(value)
            if "_POSTURE_FINDING_TYPES" in targets and isinstance(node.value, ast.Tuple):
                found.update(v for e in node.value.elts if (v := _literal(e)))
            if rel == "capabilities/monitoring/snapshots.py" and (value := _literal(node.value)):
                if value.startswith("monitor_"):
                    found.add(value)
        if isinstance(node, ast.Dict) and rel in ISSUE_MODULES:
            for key, value in zip(node.keys, node.values, strict=True):
                if key is not None and _literal(key) == "type" and (v := _literal(value)):
                    found.add(v)
    return found


def used_in_src() -> set[str]:
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        found |= _types_in(path)
    return found


def test_the_scan_finds_the_types_it_should():
    """Guards the scan itself: a scan that finds nothing passes everything."""
    used = used_in_src()
    for expected in (
        "shadow_agent",  # a raise_finding literal
        "containment",  # a FINDING_TYPE constant
        "binding_commitment",  # an evidence issue from a check
        "tool_poisoning",  # an MCP scan issue
        "skill_poisoning",  # a skill scan issue
        "monitor_failing",  # a monitoring condition
        "stale_identity",  # an identity posture
    ):
        assert expected in used
    assert len(used) >= 60


def test_every_finding_type_used_in_src_is_registered():
    unregistered = sorted(t for t in used_in_src() if not finding_types.is_registered(t))
    assert unregistered == [], f"register these in platform/ledger/finding_types.py: {unregistered}"


def test_every_registered_type_is_complete():
    for entry in finding_types.all_types():
        assert entry.title and entry.description and entry.owner, entry
        assert entry.severity in finding_types.SEVERITIES, entry


def test_an_unregistered_type_is_refused_in_strict_mode(session):
    with pytest.raises(finding_types.UnregisteredFindingType):
        raise_finding(session, type="not_a_real_type", title="x")


def test_production_only_warns(session, monkeypatch, caplog):
    monkeypatch.delenv(finding_types.STRICT_ENV, raising=False)
    with caplog.at_level(logging.WARNING):
        finding, created = raise_finding(session, type="also_not_real", title="x")
    assert created and finding.type == "also_not_real"
    assert "also_not_real" in caplog.text


def test_a_pack_declares_its_own_types(tmp_path, monkeypatch):
    from agentfox.platform import packs

    pack = tmp_path / ".agentfox" / "packs" / "acme" / "claims"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        "id: acme/claims\nversion: 0.1.0\nmaturity: stable\nowners: [acme]\n"
        "finding_types:\n"
        "  - {type: claims_overpay, title: Claim overpaid, severity: high,"
        " description: A claim was paid above its limit.}\n"
    )
    monkeypatch.chdir(tmp_path)
    packs.clear_cache()
    finding_types.reset_pack_types()
    try:
        entry = finding_types.get("claims_overpay")
        assert entry is not None and entry.owner == "pack:acme/claims"
    finally:
        packs.clear_cache()
        finding_types.reset_pack_types()


def test_the_api_lists_the_registry(client):
    response = client.get("/api/findings/types")
    assert response.status_code == 200
    rows = {row["type"]: row for row in response.json()["types"]}
    assert rows["shadow_agent"]["title"] == "Unregistered agent"
    assert set(rows) >= {t.type for t in finding_types.BUILTIN}
