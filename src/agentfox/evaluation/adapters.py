"""promptfoo adapter (P4-1).

Appendix A.1 picks promptfoo as the wrapped eval runner: MIT, actively maintained,
and purpose-built for regression gating in CI — exactly the Phase-0 feature. We wrap
it rather than rebuild it, and our value-add is what the catalog says it is: domain
scorers, silent-failure detection, and the compliance tie-in.

It stays *off* the critical path (the native runner is the default) for one concrete
reason: promptfoo is a Node tool, and requiring a Node toolchain inside a regulated
customer's air-gapped Python deployment would violate NFR-4/NFR-9. Where it is
present, it is used; where it is not, nothing is lost.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox import __version__
from agentfox.core.config import get_settings
from agentfox.core.models import EvalCase, EvalResult, EvalRun, EvalSuite, utcnow


class PromptfooRunner:
    name = "promptfoo"

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or get_settings().promptfoo_bin

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def build_config(
        self, session: Session, suite: EvalSuite, target: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate our suite into a promptfoo config.

        Assertion mapping is intentionally partial: promptfoo's built-in assertions
        cover exact/contains/regex/schema well, and our groundedness and
        silent-failure scorers have no promptfoo equivalent — so those are always
        computed on our side, whichever runner produced the outputs.
        """
        cases = list(session.scalars(select(EvalCase).where(EvalCase.suite_id == suite.id)))
        tests = []
        for case in cases:
            data = case.input_json or {}
            expected = case.expected_json or {}
            assertions: list[dict[str, Any]] = []
            if expected.get("output"):
                assertions.append({"type": "equals", "value": expected["output"]})
            for needle in expected.get("contains") or []:
                assertions.append({"type": "contains", "value": needle})
            if expected.get("pattern"):
                assertions.append({"type": "regex", "value": expected["pattern"]})
            if expected.get("schema"):
                assertions.append({"type": "is-json", "value": expected["schema"]})
            tests.append(
                {
                    "description": case.id,
                    "vars": {"prompt": data.get("prompt", ""), **(case.context_json or {})},
                    "assert": assertions or [{"type": "javascript", "value": "true"}],
                }
            )
        return {
            "description": f"{suite.name or suite.key} (exported from AgentFox)",
            "prompts": ["{{prompt}}"],
            "providers": [f"{target.get('provider', 'echo')}:{target.get('model', 'default')}"],
            "tests": tests,
        }

    def run(
        self,
        session: Session,
        suite: EvalSuite,
        target: dict[str, Any],
        scorers: list[str] | None = None,
    ) -> EvalRun:
        run = EvalRun(
            suite_id=suite.id,
            target_json=target,
            scorer_keys=list(scorers or ["promptfoo"]),
            status="running",
            runner=self.name,
            mode="offline",
            started_at=utcnow(),
            code_version=__version__,
        )
        session.add(run)
        session.flush()

        if not self.available():
            run.status = "skipped"
            run.finished_at = utcnow()
            run.summary_json = {
                "skipped": True,
                "reason": (
                    f"'{self.binary}' not found on PATH. promptfoo is an optional "
                    "wrapped runner; the native runner is the default (Appendix A.1)."
                ),
            }
            session.flush()
            return run

        config = self.build_config(session, suite, target)
        with tempfile.TemporaryDirectory() as tmp:  # pragma: no cover - needs the binary
            directory = Path(tmp)
            (directory / "promptfooconfig.yaml").write_text(yaml.safe_dump(config))
            output = directory / "results.json"
            proc = subprocess.run(  # noqa: S603
                [
                    self.binary,
                    "eval",
                    "-c",
                    "promptfooconfig.yaml",
                    "-o",
                    str(output),
                    "--no-progress-bar",
                ],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=1800,
            )
            if output.exists():
                self._ingest(session, run, json.loads(output.read_text()))
                run.status = "completed"
            else:
                run.status = "failed"
                run.summary_json = {"error": proc.stderr[-4000:]}
        run.finished_at = utcnow()
        session.flush()
        return run

    @staticmethod
    def _ingest(
        session: Session, run: EvalRun, payload: dict[str, Any]
    ) -> None:  # pragma: no cover
        results = (payload.get("results") or {}).get("results") or payload.get("results") or []
        passed = 0
        for row in results:
            case_id = str((row.get("testCase") or {}).get("description") or "")
            success = bool(row.get("success"))
            passed += int(success)
            session.add(
                EvalResult(
                    run_id=run.id,
                    case_id=case_id,
                    scorer_key="promptfoo",
                    score=1.0 if success else 0.0,
                    passed=success,
                    output_json={"output": str(row.get("response", {}).get("output", ""))[:4000]},
                    detail_json={"gradingResult": row.get("gradingResult")},
                )
            )
        total = len(results)
        run.summary_json = {
            "cases": total,
            "scorers": {
                "promptfoo": {
                    "mean": round(passed / total, 4) if total else 0.0,
                    "pass_rate": round(passed / total, 4) if total else 0.0,
                    "n": total,
                }
            },
        }


def get_runner(name: str | None = None):
    """Resolve an :class:`EvalRunner` by name, falling back to native."""
    from agentfox.evaluation.runner import NativeEvalRunner

    choice = name or get_settings().eval_runner
    if choice == "promptfoo":
        runner = PromptfooRunner()
        if runner.available():
            return runner
    return NativeEvalRunner()


def available_runners() -> dict[str, bool]:
    return {"native": True, "promptfoo": PromptfooRunner().available()}
