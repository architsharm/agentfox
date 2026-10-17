"""The stock Rego/Cedar libraries and the manifest schemas ship as data, with notices.

`opa test` and `cedar run-tests` run the libraries' own test suites when those
binaries are installed; otherwise those two tests skip.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import agentfox.platform.policy as policy_pkg

POLICY_DIR = Path(policy_pkg.__file__).parent
STDLIB = POLICY_DIR / "stdlib"
SCHEMA = POLICY_DIR / "compat" / "schema"
NOTICE = "Copyright (c) Microsoft Corporation."


def test_every_rego_module_has_its_tests_and_the_notice():
    modules = sorted(p for p in (STDLIB / "rego").glob("*.rego") if not p.stem.endswith("_test"))
    assert len(modules) == 11
    for module in modules:
        assert (module.parent / f"{module.stem}_test.rego").is_file(), module.name
    for path in (STDLIB / "rego").glob("*.rego"):
        assert NOTICE in path.read_text().splitlines()[0], path.name


def test_every_cedar_policy_has_its_tests_and_the_notice():
    policies = sorted((STDLIB / "cedar").glob("*.cedar"))
    assert len(policies) == 10
    for path in policies:
        assert NOTICE in path.read_text().splitlines()[0], path.name
        json.loads((path.parent / f"{path.stem}_test.json").read_text())


def test_the_schemas_parse_and_carry_the_license():
    schemas = sorted(SCHEMA.rglob("*.json"))
    assert len(schemas) == 9
    for path in schemas:
        assert json.loads(path.read_text()).get("$schema"), path.name
    for directory in (STDLIB, SCHEMA):
        text = (directory / "LICENSE").read_text()
        assert "MIT License" in text and NOTICE in text
        assert (directory / "README.md").is_file()


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa is not on PATH")
def test_opa_runs_the_rego_library_tests():
    result = subprocess.run(
        ["opa", "test", str(STDLIB / "rego")], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("cedar") is None, reason="cedar is not on PATH")
def test_cedar_runs_the_cedar_library_tests():
    for path in sorted((STDLIB / "cedar").glob("*.cedar")):
        result = subprocess.run(
            [
                "cedar",
                "run-tests",
                "--policies",
                str(path),
                "--tests",
                str(path.with_name(f"{path.stem}_test.json")),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (path.name, result.stdout + result.stderr)
