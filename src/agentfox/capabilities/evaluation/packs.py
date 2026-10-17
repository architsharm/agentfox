"""Testing and validating a capability pack: its golden cases, and everything else it ships.

A pack's ``cases/*.yaml`` hold golden events with the outcome the pack promises. They
run offline, with no database: a policy case evaluates the pack's policies with the
native engine, a ladder case evaluates one of its ladders, a compile case runs the
policy compiler over a sentence. `run_pack_cases` runs them; `validate_pack` also checks
the manifest, that every policy loads and lints clean, that ladders, probes and
controls parse, that check files import, that required detectors exist, and that a
``stable`` pack meets the quality bar (owners, a README, at least one case).

Case file shape::

    cases:
      - name: an injected instruction on input is blocked
        kind: policy                 # policy (default) | ladder | compile | fallback | control
        event: {surface: input, detections: [{entity_type: INJECTION.X, score: 0.95}]}
        expect: {verdict: block, rules: [injection.direct], not_rules: []}
      - name: a 50 dollar refund is verified first
        kind: ladder
        ladder: refund-approval
        request: {arguments: {amount: 50}}
        expect: {outcome: verify}

``verdict`` is the effective verdict: what the policies would do with every one of
them enforcing, so a case does not depend on the mode a pack ships in. A policy case
evaluates the pack's own policies, or the loaded packs' policies named in
``policies:``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agentfox.platform.packs import (
    MATURITIES,
    Pack,
    PackError,
    fallback_policy_packs,
    load_packs,
    read_pack,
)
from agentfox.platform.policy import PolicyDocument, PolicyInput, combine
from agentfox.platform.policy.engine import NativePolicyEngine
from agentfox.platform.policy.hierarchy import lint_documents

#: Imports a pack's ``checks/*.py`` may make: the layers at or below capabilities.
CHECK_IMPORTS_ALLOWED = ("agentfox.core", "agentfox.platform", "agentfox.capabilities")

CASE_KINDS = ("policy", "ladder", "compile", "fallback", "control")


@dataclass
class CaseResult:
    pack: str
    file: str
    name: str
    kind: str
    passed: bool
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "pack": self.pack,
            "file": self.file,
            "name": self.name,
            "kind": self.kind,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class PackReport:
    pack: str
    path: str
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and all(c.passed for c in self.cases)

    def to_json(self) -> dict[str, Any]:
        return {
            "pack": self.pack,
            "path": self.path,
            "ok": self.ok,
            "problems": self.problems,
            "warnings": self.warnings,
            "cases": [c.to_json() for c in self.cases],
        }


def policies_of(pack: Pack) -> list[PolicyDocument]:
    return [PolicyDocument.from_yaml(path.read_text()) for path in pack.files("policies")]


def ladders_of(pack: Pack) -> dict[str, Any]:
    from agentfox.capabilities.business.ladder import Ladder

    out: dict[str, Any] = {}
    for path in pack.files("ladders"):
        ladder = Ladder.model_validate(yaml.safe_load(path.read_text()) or {})
        out[ladder.key] = ladder
        out.setdefault(path.stem, ladder)
    return out


def cases_of(pack: Pack) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in pack.files("cases"):
        data = yaml.safe_load(path.read_text()) or {}
        for case in data.get("cases") or []:
            out.append((path, case if isinstance(case, dict) else {"_invalid": case}))
    return out


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _policy_case(pack: Pack, case: dict[str, Any]) -> tuple[bool, str]:
    names = case.get("policies")
    if names:
        available = {doc.key: doc for other in load_packs() for doc in policies_of(other)}
        available.update({doc.key: doc for doc in policies_of(pack)})
        missing = [n for n in names if n not in available]
        if missing:
            return False, f"no loaded pack has policy {', '.join(missing)}"
        documents = [available[n] for n in names]
    else:
        documents = policies_of(pack)
    if not documents:
        return False, "the pack has no policies to evaluate"
    event = PolicyInput(**(case.get("event") or {}))
    engine = NativePolicyEngine()
    merged = combine([engine.evaluate(doc, event) for doc in documents])
    fired = [rule.rule_id for rule in merged.rules_fired]
    expect = case.get("expect") or {}
    wrong: list[str] = []
    if "verdict" in expect and merged.effective_verdict != expect["verdict"]:
        wrong.append(f"verdict {merged.effective_verdict}, expected {expect['verdict']}")
    missing = [r for r in expect.get("rules") or [] if r not in fired]
    if missing:
        wrong.append(f"did not fire {', '.join(missing)}")
    unwanted = [r for r in expect.get("not_rules") or [] if r in fired]
    if unwanted:
        wrong.append(f"fired {', '.join(unwanted)}")
    detail = "; ".join(wrong) or f"{merged.effective_verdict} ({', '.join(fired) or 'no rule'})"
    return not wrong, detail


def _ladder_case(pack: Pack, case: dict[str, Any]) -> tuple[bool, str]:
    from agentfox.capabilities.business.ladder import evaluate

    ladders = ladders_of(pack)
    ladder = ladders.get(str(case.get("ladder")))
    if ladder is None:
        return False, f"no ladder {case.get('ladder')!r} in the pack"
    decision = evaluate(ladder, case.get("request") or {})
    want = (case.get("expect") or {}).get("outcome")
    return decision.outcome == want, f"outcome {decision.outcome}, expected {want}"


def _compile_case(pack: Pack, case: dict[str, Any]) -> tuple[bool, str]:
    from agentfox.capabilities.business.compile import compile_document

    result = compile_document(str(case.get("text") or "")).to_json()
    tools = [r["definition"].get("tool") for r in result["rules"] if r.get("definition")]
    roles = [
        band.get("approver_role")
        for r in result["rules"]
        for band in (r.get("definition") or {}).get("bands") or []
        if band.get("approver_role")
    ]
    expect = case.get("expect") or {}
    wrong: list[str] = []
    if "tool" in expect and expect["tool"] not in tools:
        wrong.append(f"tools {tools}, expected {expect['tool']}")
    if "approver_role" in expect and expect["approver_role"] not in roles:
        wrong.append(f"approver roles {roles}, expected {expect['approver_role']}")
    return not wrong, "; ".join(wrong) or f"tools {tools}, roles {roles}"


def _fallback_case(pack: Pack, case: dict[str, Any]) -> tuple[bool, str]:
    keys = [
        doc.key
        for chosen in fallback_policy_packs(case.get("risk_tier"))
        for doc in policies_of(chosen)
    ]
    want = list((case.get("expect") or {}).get("policies") or [])
    return keys == want, f"fallback {keys}, expected {want}"


def _control_case(pack: Pack, case: dict[str, Any]) -> tuple[bool, str]:
    from agentfox.capabilities.compliance.catalog import load_catalog

    path = pack.file("controls", "controls.yaml")
    directory = path.parent if path else None
    controls = {c.get("key"): c for c in load_catalog(directory).get("controls") or []}
    control = controls.get(case.get("control"))
    if control is None:
        return False, f"no control {case.get('control')!r} in the pack"
    want = list((case.get("expect") or {}).get("frameworks") or [])
    mapped = list((control.get("mappings") or {}).keys())
    missing = [f for f in want if f not in mapped]
    return not missing, f"mapped to {mapped}" + (f"; missing {missing}" if missing else "")


_RUNNERS = {
    "policy": _policy_case,
    "ladder": _ladder_case,
    "compile": _compile_case,
    "fallback": _fallback_case,
    "control": _control_case,
}


def run_case(pack: Pack, path: Path, case: dict[str, Any]) -> CaseResult:
    kind = str(case.get("kind") or "policy")
    name = str(case.get("name") or "(unnamed)")
    runner = _RUNNERS.get(kind)
    if runner is None:
        passed, detail = False, f"unknown case kind {kind!r} (one of {', '.join(CASE_KINDS)})"
    else:
        try:
            passed, detail = runner(pack, case)
        except Exception as exc:
            passed, detail = False, f"{type(exc).__name__}: {exc}"
    return CaseResult(pack.id, path.name, name, kind, passed, detail)


def run_pack_cases(pack: Pack) -> list[CaseResult]:
    """Run every golden case in the pack."""
    return [run_case(pack, path, case) for path, case in cases_of(pack)]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _check_imports(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError as exc:
        return [f"{path.name}: does not parse — {exc}"]
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        for module in modules:
            if module.startswith("agentfox") and not module.startswith(CHECK_IMPORTS_ALLOWED):
                problems.append(
                    f"{path.name}: imports {module}; a pack check may import only "
                    f"{', '.join(CHECK_IMPORTS_ALLOWED)}"
                )
    return problems


def validate_pack(pack_or_path: Pack | Path, *, run_cases: bool = True) -> PackReport:
    """Everything `agentfox policy packs validate` checks, for one pack."""
    if isinstance(pack_or_path, Pack):
        pack = pack_or_path
    else:
        try:
            pack = read_pack(Path(pack_or_path), "path")
        except PackError as exc:
            return PackReport(pack=str(pack_or_path), path=str(pack_or_path), problems=[str(exc)])
    report = PackReport(pack=pack.id, path=str(pack.root))
    manifest = pack.manifest

    documents: list[PolicyDocument] = []
    for path in pack.files("policies"):
        try:
            documents.append(PolicyDocument.from_yaml(path.read_text()))
        except Exception as exc:
            report.problems.append(f"policies/{path.name}: {' '.join(str(exc).split())}")
    for finding in lint_documents(documents) if documents else []:
        line = (
            f"policy lint {finding.code} ({finding.severity}) {finding.rule_id}: {finding.message}"
        )
        if finding.severity in ("critical", "high"):
            report.problems.append(line)
        else:
            report.warnings.append(line)

    try:
        ladders_of(pack)
    except Exception as exc:
        report.problems.append(f"ladders: {' '.join(str(exc).split())}")

    from agentfox.capabilities.evaluation.redteam import Probe

    for path in pack.files("probes"):
        try:
            for spec in (yaml.safe_load(path.read_text()) or {}).get("probes") or []:
                Probe(**spec)
        except Exception as exc:
            report.problems.append(f"probes/{path.name}: {' '.join(str(exc).split())}")

    for path in pack.files("controls"):
        try:
            data = yaml.safe_load(path.read_text())
            if not isinstance(data, dict):
                report.problems.append(f"controls/{path.name}: top level must be a mapping")
        except yaml.YAMLError as exc:
            report.problems.append(f"controls/{path.name}: does not parse — {exc}")

    for path in pack.files("checks", "*.py"):
        report.problems.extend(f"checks/{p}" for p in _check_imports(path))

    if manifest.requires_detectors:
        from agentfox.capabilities.detection import all_detectors

        known = set(all_detectors())
        unknown = [d for d in manifest.requires_detectors if d not in known]
        if unknown:
            report.problems.append(f"requires unknown detector(s): {', '.join(unknown)}")

    cases = cases_of(pack)
    if manifest.maturity == "stable":
        if pack.readme is None:
            report.problems.append("a stable pack needs a README.md")
        if not cases:
            report.problems.append("a stable pack needs at least one case in cases/")
    elif MATURITIES.index(manifest.maturity) and not cases:
        report.warnings.append("no cases yet; a pack needs cases to become stable")

    if run_cases:
        report.cases = [run_case(pack, path, case) for path, case in cases]
    return report


__all__ = [
    "CASE_KINDS",
    "CHECK_IMPORTS_ALLOWED",
    "CaseResult",
    "PackReport",
    "cases_of",
    "ladders_of",
    "policies_of",
    "run_case",
    "run_pack_cases",
    "validate_pack",
]
