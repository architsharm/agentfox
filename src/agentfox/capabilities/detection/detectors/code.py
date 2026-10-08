"""Insecure code an agent is about to write or run.

Action analysis (`actions.py`) reads what a *command* will do — a `DROP TABLE`, a
`rm -rf`. A coding agent's other output is a file: the code it writes is executed
later, by someone else, with nobody re-reading it. This detector reads the code in a
tool call's arguments for the patterns static analysers flag first — the same idea as
Meta's CodeShield, in deterministic, offline form:

  shell injection · eval of strings · unsafe deserialisation · TLS verification off ·
  SQL built by string concatenation · world-writable permissions · weak hashing

Each match is a `CODE.<RULE>` detection with its CWE. A policy acts on them
(the `agent-integrity` pack ships the rules, watching), so this never decides.

Tool arguments reach the pipeline as JSON, where every quote is escaped; the string
values are decoded and scanned one by one, so `verify=False` inside a file body is
seen as written.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    redact_sample,
)


@dataclass(frozen=True)
class CodeRule:
    entity: str
    cwe: str
    pattern: re.Pattern[str]
    score: float


def _rule(entity: str, cwe: str, pattern: str, score: float = 0.8) -> CodeRule:
    return CodeRule(f"CODE.{entity}", cwe, re.compile(pattern, re.IGNORECASE | re.MULTILINE), score)


RULES: tuple[CodeRule, ...] = (
    _rule(
        "SHELL_INJECTION",
        "CWE-78",
        r"subprocess\.\w+\([^)]*shell\s*=\s*True|\bos\.(?:system|popen)\s*\(|child_process\.exec(?:Sync)?\s*\(",
    ),
    _rule(
        "EVAL",
        "CWE-95",
        r"(?<![\w.])(?:eval|exec)\s*\(\s*(?![\"'][^\"']*[\"']\s*\))|new\s+Function\s*\(",
    ),
    _rule(
        "DESERIALIZATION",
        "CWE-502",
        r"\bpickle\.loads?\s*\(|\bmarshal\.loads\s*\(|\byaml\.load\s*\((?![^)]*Loader\s*=\s*(?:yaml\.)?SafeLoader)",
    ),
    _rule(
        "TLS_DISABLED",
        "CWE-295",
        r"\bverify\s*=\s*False\b|rejectUnauthorized\s*:\s*false|InsecureSkipVerify\s*:\s*true|CURLOPT_SSL_VERIFYPEER\s*,\s*(?:0|false)",
    ),
    _rule(
        "SQL_CONCAT",
        "CWE-89",
        r"\b(?:execute|executemany|query|raw)\s*\(\s*(?:f[\"'][^\"']*\b(?:select|insert|update|delete)\b[^\"']*\{|[\"'][^\"']*\b(?:select|insert|update|delete)\b[^\"']*[\"']\s*(?:\+|%\s|\.format\())",
    ),
    _rule(
        "PERMISSIVE_PERMISSIONS",
        "CWE-732",
        r"\bchmod\s+(?:-R\s+)?0?777\b|os\.chmod\s*\([^)]*0o?777",
        0.7,
    ),
    _rule(
        "WEAK_HASH",
        "CWE-328",
        r"\bhashlib\.(?:md5|sha1)\s*\(|createHash\(\s*[\"'](?:md5|sha1)[\"']",
        0.5,
    ),
)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


class InsecureCodeDetector(BaseDetector):
    key = "code.insecure"
    version = "1.0"
    surfaces = ("tool_args",)
    covers_threats = ("LLM05",)  # OWASP LLM Top 10: improper output handling
    # Matches what was written; decoded variants are not a code-review concern.
    handles_views = True

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        try:
            texts = _strings(json.loads(content))
        except (ValueError, TypeError):
            texts = [content]
        out: list[Detection] = []
        seen: set[str] = set()
        for text in texts:
            if len(text) < 8:
                continue
            for rule in RULES:
                if rule.entity in seen:
                    continue
                m = rule.pattern.search(text)
                if m is None:
                    continue
                seen.add(rule.entity)
                out.append(
                    Detection(
                        entity_type=rule.entity,
                        score=rule.score,
                        sample=redact_sample(m.group(0)[:80]),
                        detail={"cwe": rule.cwe, "tool": context.tool_key},
                    )
                )
        return out
