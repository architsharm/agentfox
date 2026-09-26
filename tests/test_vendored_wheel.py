from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = REPO_ROOT / "src" / "agentfox"
VENDOR_DIR = REPO_ROOT / "api" / "vendor"


def _source_module_files(package_dir: Path) -> set[str]:
    return {
        path.relative_to(package_dir.parent).as_posix()
        for path in package_dir.rglob("*.py")
    }


def _wheel_module_files(wheel_path: Path) -> set[str]:
    with ZipFile(wheel_path) as wheel:
        return {
            name
            for name in wheel.namelist()
            if name.startswith("agentfox/") and name.endswith(".py")
        }


def _assert_module_sets_match(source_modules: set[str], wheel_modules: set[str]) -> None:
    missing_from_wheel = sorted(source_modules - wheel_modules)
    stale_in_wheel = sorted(wheel_modules - source_modules)

    differences: list[str] = []
    if missing_from_wheel:
        differences.append(
            "Missing from vendored wheel:\n  " + "\n  ".join(missing_from_wheel)
        )
    if stale_in_wheel:
        differences.append(
            "Present only in vendored wheel:\n  " + "\n  ".join(stale_in_wheel)
        )

    assert not differences, (
        "Vendored wheel module list does not match src/agentfox. "
        "Rebuild it with `uv build --wheel --out-dir api/vendor`.\n\n"
        + "\n\n".join(differences)
    )


def test_vendored_agentfox_wheel_matches_source() -> None:
    wheels = sorted(VENDOR_DIR.glob("agentfox-*.whl"))
    assert len(wheels) == 1, (
        "Expected exactly one vendored agentfox wheel in api/vendor, "
        f"found {len(wheels)}: {[wheel.name for wheel in wheels]}"
    )

    _assert_module_sets_match(
        _source_module_files(SOURCE_PACKAGE),
        _wheel_module_files(wheels[0]),
    )


def test_wheel_check_reports_missing_source_module(tmp_path: Path) -> None:
    source_modules = {
        "agentfox/__init__.py",
        "agentfox/new_module.py",
    }
    scratch_wheel = tmp_path / "agentfox-test-py3-none-any.whl"

    with ZipFile(scratch_wheel, "w", compression=ZIP_DEFLATED) as wheel:
        wheel.writestr("agentfox/__init__.py", "")

    with pytest.raises(AssertionError, match="agentfox/new_module.py"):
        _assert_module_sets_match(source_modules, _wheel_module_files(scratch_wheel))
