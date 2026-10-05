from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = REPO_ROOT / "src" / "agentfox"
VENDOR_DIR = REPO_ROOT / "api" / "vendor"
VENDOR_DIRS = (
    VENDOR_DIR,
    REPO_ROOT / "demo" / "redteam-live-lang" / "vendor",
)


#: Copied into the wheel from the repository root rather than living under
#: `src/agentfox` (see the force-include in pyproject.toml, which exists so that
#: `agentfox db upgrade` works for someone who installed from PyPI). They are
#: legitimately in the wheel and legitimately not in the source package, so this
#: comparison has to know about them or it reports the fix as staleness.
FORCE_INCLUDED = ("agentfox/_migrations/",)


def _source_module_contents(package_dir: Path) -> dict[str, bytes]:
    return {
        path.relative_to(package_dir.parent).as_posix(): path.read_bytes()
        for path in package_dir.rglob("*.py")
    }


def _wheel_module_contents(wheel_path: Path) -> dict[str, bytes]:
    with ZipFile(wheel_path) as wheel:
        return {
            name: wheel.read(name)
            for name in wheel.namelist()
            if name.startswith("agentfox/")
            and name.endswith(".py")
            and not name.startswith(FORCE_INCLUDED)
        }


def _assert_module_contents_match(
    source_modules: dict[str, bytes], wheel_modules: dict[str, bytes]
) -> None:
    source_names = set(source_modules)
    wheel_names = set(wheel_modules)
    missing_from_wheel = sorted(source_names - wheel_names)
    stale_in_wheel = sorted(wheel_names - source_names)
    content_mismatches = sorted(
        name for name in source_names & wheel_names if source_modules[name] != wheel_modules[name]
    )

    newline = "\n"
    differences: list[str] = []
    if missing_from_wheel:
        differences.append(
            "Missing from vendored wheel:" + newline + "  " + newline.join(missing_from_wheel)
        )
    if stale_in_wheel:
        differences.append(
            "Present only in vendored wheel:" + newline + "  " + newline.join(stale_in_wheel)
        )
    if content_mismatches:
        differences.append(
            "Content differs for:" + newline + "  " + newline.join(content_mismatches)
        )

    assert not differences, (
        "Vendored wheel modules do not match src/agentfox. Rebuild both with "
        "uv build --wheel --out-dir api/vendor and "
        "uv build --wheel --out-dir demo/redteam-live-lang/vendor."
        + newline
        + newline
        + (newline + newline).join(differences)
    )


@pytest.mark.parametrize("vendor_dir", VENDOR_DIRS, ids=("api", "redteam-live-lang"))
def test_vendored_agentfox_wheel_matches_source(vendor_dir: Path) -> None:
    wheels = sorted(vendor_dir.glob("agentfox-*.whl"))
    assert len(wheels) == 1, (
        f"Expected exactly one vendored agentfox wheel in {vendor_dir}, "
        f"found {len(wheels)}: {[wheel.name for wheel in wheels]}"
    )

    _assert_module_contents_match(
        _source_module_contents(SOURCE_PACKAGE), _wheel_module_contents(wheels[0])
    )


def test_wheel_check_reports_missing_source_module(tmp_path: Path) -> None:
    source_modules = {
        "agentfox/__init__.py": b"",
        "agentfox/new_module.py": b"",
    }
    scratch_wheel = tmp_path / "agentfox-test-py3-none-any.whl"

    with ZipFile(scratch_wheel, "w", compression=ZIP_DEFLATED) as wheel:
        wheel.writestr("agentfox/__init__.py", "")

    with pytest.raises(AssertionError, match="agentfox/new_module.py"):
        _assert_module_contents_match(source_modules, _wheel_module_contents(scratch_wheel))


def test_wheel_check_reports_stale_module_contents(tmp_path: Path) -> None:
    source_modules = {"agentfox/submit.py": b"new source contents"}
    scratch_wheel = tmp_path / "agentfox-test-py3-none-any.whl"

    with ZipFile(scratch_wheel, "w", compression=ZIP_DEFLATED) as wheel:
        wheel.writestr("agentfox/submit.py", b"stale wheel contents")

    with pytest.raises(AssertionError, match="agentfox/submit.py"):
        _assert_module_contents_match(source_modules, _wheel_module_contents(scratch_wheel))


def test_the_wheel_carries_the_migrations_it_is_supposed_to() -> None:
    """The other half of excluding them above.

    `_wheel_module_files` now ignores `agentfox/_migrations/`, so dropping the
    force-include would make the comparison pass while producing a wheel whose
    `agentfox db upgrade` dies exactly as 0.3.1's did. This asserts they are in
    there, and that alembic has what it needs to run them.
    """
    wheel_path = sorted(VENDOR_DIR.glob("agentfox-*.whl"))[0]
    with ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    assert "agentfox/_alembic.ini" in names
    assert "agentfox/_migrations/env.py" in names
    revisions = [n for n in names if n.startswith("agentfox/_migrations/versions/")]
    assert len(revisions) == len(list((REPO_ROOT / "migrations" / "versions").glob("*.py")))
