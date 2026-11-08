"""The Python rule titles mirror the dashboard's, so a refusal raised in the user's
process names a rule the way the dashboard does."""

from __future__ import annotations

import re
from pathlib import Path

from agentfox.core.rule_titles import RULE_TITLES, rule_title

VOCAB = Path(__file__).resolve().parents[2] / "dashboard" / "lib" / "product" / "vocab.ts"


def test_the_titles_match_the_dashboards():
    body = VOCAB.read_text().split("const RULE_TITLES", 1)[1].split("\n};", 1)[0]
    dashboard = dict(re.findall(r'^\s+"([^"]+)": "((?:[^"\\]|\\.)*)",', body, re.M))
    assert dashboard == RULE_TITLES


def test_an_unknown_rule_falls_back_like_the_dashboard():
    assert rule_title("injection.direct") == "Jailbreaks & prompt injection"
    assert rule_title("pii.email_outbound") == "Email outbound"
    assert rule_title("custom.no-rivals", "No rivals: your rule") == "No rivals"
