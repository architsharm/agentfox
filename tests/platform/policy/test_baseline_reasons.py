"""No shipped pack's reasons claim their action was taken.

The baseline pack watches by default, and a watching rule records the same reason for
a reply it let through: a run showed "Personal data detected in the response; redacted
before delivery." while the app printed the SSN and card number. The regional and
industry packs start in observe too, so the same holds for every shipped pack: a
reason says what was found and what the action is for, never that it happened.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

import agentfox

PACKS = Path(agentfox.__file__).parent / "packs"
BASELINE = PACKS / "baseline" / "policies" / "baseline.yaml"
_DONE = re.compile(r"\b(?:blocked|redacted|tokeni[sz]ed|masked|refused|denied)\b", re.I)

#: Every shipped policy file (the `_template` pack is scaffolding, not shipped rules).
POLICY_FILES = sorted(p for p in PACKS.rglob("policies/*.yaml") if "_template" not in p.parts)
#: The translated rule tables, whose reasons are the risk details the policies act on.
TABLE_FILES = sorted(PACKS.rglob("checks/rules.py"))


def _table(path: Path):
    spec = importlib.util.spec_from_file_location("reasons_" + path.parent.parent.name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from agentfox.platform import checks as checks_registry

    pack_id = "/".join(path.parent.parent.relative_to(PACKS).parts)
    checks_registry.unregister("pack." + pack_id.replace("/", "."))
    return module.TABLES


def test_no_baseline_reason_says_its_action_happened():
    doc = yaml.safe_load(BASELINE.read_text())
    claims = {r["id"]: r["reason"] for r in doc["rules"] if _DONE.search(r.get("reason", ""))}
    assert claims == {}


def test_every_shipped_pack_is_checked():
    packs = {p.relative_to(PACKS).parts[0] for p in POLICY_FILES}
    assert {"baseline", "industry", "regional"} <= packs
    assert len(POLICY_FILES) > 20


@pytest.mark.parametrize("path", POLICY_FILES, ids=lambda p: str(p.relative_to(PACKS)))
def test_no_pack_reason_says_its_action_happened(path):
    doc = yaml.safe_load(path.read_text()) or {}
    claims = {
        r["id"]: r["reason"]
        for r in doc.get("rules") or []
        if _DONE.search(str(r.get("reason") or ""))
    }
    assert claims == {}


@pytest.mark.parametrize("path", TABLE_FILES, ids=lambda p: str(p.relative_to(PACKS)))
def test_no_translated_rule_reason_says_its_action_happened(path):
    claims = {
        rule.code: rule.reason
        for rules in _table(path).values()
        for rule in rules
        if _DONE.search(rule.reason)
    }
    assert claims == {}
