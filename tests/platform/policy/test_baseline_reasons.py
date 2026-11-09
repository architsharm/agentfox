"""The baseline pack's reasons never claim their action was taken.

The baseline pack watches by default, and a watching rule records the same reason for
a reply it let through: a run showed "Personal data detected in the response; redacted
before delivery." while the app printed the SSN and card number.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

import agentfox

BASELINE = Path(agentfox.__file__).parent / "packs" / "baseline" / "policies" / "baseline.yaml"
_DONE = re.compile(r"\b(?:blocked|redacted|tokeni[sz]ed|masked|refused)\b", re.I)


def test_no_baseline_reason_says_its_action_happened():
    doc = yaml.safe_load(BASELINE.read_text())
    claims = {r["id"]: r["reason"] for r in doc["rules"] if _DONE.search(r.get("reason", ""))}
    assert claims == {}
