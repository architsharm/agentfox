"""The wheel each requirements.txt installs has to exist, and be the only one.

Two deployments install the vendored wheel by exact filename — `api/` on Vercel
and `demo/redteam-live-lang/`. Nothing in the repository checked that the
filename on those lines corresponds to a file that is actually there.

Found on the 0.3.0 -> 0.3.1 bump, which is the case that makes it bite. A
version bump changes the wheel's NAME, and four places pinned the old one: both
`requirements.txt` files and, worse, both `vendor/.gitignore` negations. The
gitignore pin is the silent half — the freshly built wheel is ignored, so it is
never committed, the previous release stays tracked, and the deploy carries on
installing old code with nothing failing anywhere. That is the same class of
failure as the month-long stale gateway (#16), reached by a different route.

The gitignores are `!agentfox-*.whl` now so any version is trackable. These
tests cover the other half: the path is real, and there is exactly one wheel to
be ambiguous about.

Complementary to tests/test_vendored_wheel.py, which checks that the wheel's
CONTENTS match src/agentfox. This checks that the wheel the deployment names is
the wheel that exists — a correct wheel under a name nothing installs is still
a broken deploy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: (requirements file, the directory its relative wheel path resolves against).
#:
#: The leading `../` in these files is a Vercel resolver quirk, not a normal
#: relative path — its own comments explain that requirements.txt is treated as
#: one directory deeper than it is. So the wheel is located by NAME in the known
#: vendor directory rather than by resolving the string, which would follow the
#: quirk off into a directory that does not exist locally.
DEPLOYMENTS = [
    ("api/requirements.txt", "api/vendor"),
    ("demo/redteam-live-lang/requirements.txt", "demo/redteam-live-lang/vendor"),
]

WHEEL_LINE = re.compile(r"^\s*\S*?(agentfox-[^/\s]+\.whl)\s*$", re.MULTILINE)


@pytest.mark.parametrize("requirements,vendor_dir", DEPLOYMENTS)
def test_requirements_installs_a_wheel_that_exists(requirements: str, vendor_dir: str) -> None:
    req_path = REPO_ROOT / requirements
    vendor = REPO_ROOT / vendor_dir

    names = WHEEL_LINE.findall(req_path.read_text())
    assert len(names) == 1, (
        f"{requirements} should install exactly one agentfox wheel, found {names}"
    )

    wheel = vendor / names[0]
    assert wheel.is_file(), (
        f"{requirements} installs {names[0]}, which is not in {vendor_dir}/.\n"
        f"Present: {sorted(p.name for p in vendor.glob('agentfox-*.whl')) or 'nothing'}\n"
        "After a version bump, rebuild and repoint both together:\n"
        "  uv build --wheel --out-dir api/vendor\n"
        "  uv build --wheel --out-dir demo/redteam-live-lang/vendor"
    )


@pytest.mark.parametrize("_requirements,vendor_dir", DEPLOYMENTS)
def test_exactly_one_wheel_is_committed(_requirements: str, vendor_dir: str) -> None:
    """Two wheels in a vendor directory is how the wrong one gets deployed.

    A bump that leaves the old wheel behind is not obviously broken — both files
    are there, the deployment installs whichever its requirements line names,
    and which of the two that is stops being obvious from the directory.
    """
    wheels = sorted((REPO_ROOT / vendor_dir).glob("agentfox-*.whl"))
    assert len(wheels) == 1, (
        f"Expected exactly one wheel in {vendor_dir}/, found "
        f"{[w.name for w in wheels] or 'none'}. Delete the superseded one."
    )


def test_the_wheel_version_matches_the_package_version() -> None:
    """A wheel named for a version the package no longer claims is stale by
    definition, whatever its contents."""
    import tomllib

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    version = pyproject["project"]["version"]

    for _requirements, vendor_dir in DEPLOYMENTS:
        wheels = list((REPO_ROOT / vendor_dir).glob("agentfox-*.whl"))
        assert wheels, f"no wheel in {vendor_dir}/"
        assert f"agentfox-{version}-" in wheels[0].name, (
            f"{vendor_dir}/{wheels[0].name} does not match pyproject version "
            f"{version} — rebuild it."
        )
