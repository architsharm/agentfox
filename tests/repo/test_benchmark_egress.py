"""No benchmark sends dataset text to a third-party API unless the run says why."""

from __future__ import annotations

import pathlib
import re

import pytest

from benchmarks._common.egress import REAL_PERSONAL_DATA, require_egress

BENCHMARKS = pathlib.Path(__file__).resolve().parents[2] / "benchmarks"

#: what a script does when it is about to reach a hosted model
_SENDS = re.compile(r"allow_egress\s*=\s*True|JEV_API_KEY|api\.typesafe\.ai")


def test_refuses_without_a_reason(capsys):
    for reason in (None, "", "   "):
        with pytest.raises(SystemExit) as exc:
            require_egress(reason, destination="x", datasets=["pii/data/tab_echr_test.json"])
        assert "--allow-egress" in str(exc.value)
        assert "real, non-synthetic personal data" in str(exc.value)


def test_proceeds_with_a_reason(capsys):
    require_egress("re-measure presence recall", destination="x", datasets=["a.json"])
    assert "egress allowed: re-measure presence recall" in capsys.readouterr().out


def test_tab_is_listed_as_real_personal_data():
    assert "pii/data/tab_echr_test.json" in REAL_PERSONAL_DATA


def test_every_script_that_reaches_a_hosted_model_asks_first():
    offenders = [
        str(p.relative_to(BENCHMARKS))
        for p in BENCHMARKS.rglob("*.py")
        if "_common" not in p.parts
        and _SENDS.search(src := p.read_text())
        and "require_egress(" not in src
    ]
    assert offenders == []


def test_judgment_benchmark_refuses_by_default():
    from benchmarks.judgment.run_judgment_benchmark import main

    with pytest.raises(SystemExit):
        main([])
