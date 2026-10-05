"""A team's own policy packs, distributed by git rather than by a hub.

Three YAML files baked into a wheel is not a policy system. A competitor ships
`policies add <owner>/<repo>` and a public policy-hub, which is a real
distribution advantage over what we had.

We take the same result by a different route, deliberately. A hub means the
governance product reaches the network to fetch the rules it will then enforce,
on a deployment whose whole argument is that it does not reach the network. A
directory in the repository gets a team's policies travelling with their code,
arriving by `git pull`, and reviewed in a pull request like everything else —
and leaves the fetching to the operator and the supply-chain controls they
already have.

The property that makes this safe is the one tested last: a project pack can
replace a shipped pack, but it cannot use that to drop a protected rule.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agentfox.policy import (
    PolicyPackError,
    load_available,
    load_from_dir,
    pack_sources,
    project_policy_dir,
)

HOUSE = textwrap.dedent(
    """
    key: house-rules
    name: House rules
    mode: observe
    rules:
      - id: house.only
        when: {surface: [input]}
        effect: escalate
        severity: low
    """
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".agentfox" / "policies"
    directory.mkdir(parents=True)
    return directory


def test_the_convention_matches_the_config_file_convention():
    """`agentfox.toml` is already looked up in the working directory."""
    assert project_policy_dir(Path("/srv/app")) == Path("/srv/app/.agentfox/policies")


def test_a_project_pack_is_loadable_alongside_the_shipped_ones(project):
    (project / "house.yaml").write_text(HOUSE)
    keys = {doc.key for doc in load_available()}
    assert "house-rules" in keys
    assert {"baseline", "tool-containment"} <= keys, "the shipped packs are still there"


def test_nothing_changes_when_there_is_no_project_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert [d.key for d in load_available()] == [d.key for d in load_from_dir()]


def test_a_project_pack_replaces_a_shipped_pack_of_the_same_key(project):
    """Overriding `baseline` for your own deployment is the ordinary reason to
    write one, and a half-merged policy is a policy nobody can predict."""
    (project / "mine.yaml").write_text(
        textwrap.dedent(
            """
            key: baseline
            mode: enforce
            rules:
              - id: house.only_rule
                when: {surface: [input]}
                effect: block
                severity: high
            """
        )
    )
    baseline = next(d for d in load_available() if d.key == "baseline")
    assert [r.id for r in baseline.rules] == ["house.only_rule"]
    assert baseline.mode == "enforce"
    # Exactly one baseline, not two.
    assert sum(1 for d in load_available() if d.key == "baseline") == 1


def test_provenance_is_reportable(project):
    (project / "house.yaml").write_text(HOUSE)
    rows = {r["key"]: r for r in pack_sources()}
    assert rows["house-rules"]["origin"] == "project"
    assert rows["baseline"]["origin"] == "shipped"
    assert rows["house-rules"]["path"].endswith("house.yaml")


def test_an_override_is_reported_as_one(project):
    """Invisible in `policy list`, which reads the database — by then the
    shipped pack and the replacement are the same row."""
    (project / "mine.yaml").write_text("key: baseline\nrules: []\n")
    override = next(r for r in pack_sources() if r["key"] == "baseline" and r["overrides"])
    assert override["origin"] == "project"
    assert override["overrides"].endswith("baseline.yaml")


def test_a_broken_pack_names_the_file(project):
    """Otherwise it is a pydantic traceback with no filename in it, and the
    operator diffs three YAML files to find which one."""
    (project / "broken.yaml").write_text("key: [this is not a string]\n")
    with pytest.raises(PolicyPackError) as excinfo:
        load_available()
    assert "broken.yaml" in str(excinfo.value)


def test_a_project_pack_cannot_drop_a_protected_rule(project):
    """The property that makes any of this safe.

    Without it, `.agentfox/policies/tool-containment.yaml` with one harmless
    rule in it is a supported, git-tracked way to switch off the control that
    stops an agent switching off everything else.
    """
    (project / "thin.yaml").write_text(
        textwrap.dedent(
            """
            key: tool-containment
            mode: enforce
            rules:
              - id: something.else
                when: {surface: [input]}
                effect: allow
            """
        )
    )
    with pytest.raises(PolicyPackError) as excinfo:
        load_available()
    assert "control_plane.tamper" in str(excinfo.value)
