"""Finding and choosing capability packs: built in, project, entry point; maturity."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentfox.platform import checks as check_registry
from agentfox.platform import packs
from agentfox.platform.packs import PackError, PackManifest, core_satisfies

BUILTIN_IDS = [
    "agent-integrity",
    "baseline",
    "coding-agent",
    "compliance/catalog",
    "customer-support",
    "eu-ai-act",
    "payments/refunds",
    "tool-containment",
]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project directory as the working directory, with fresh pack caches."""
    monkeypatch.chdir(tmp_path)
    packs.clear_cache()
    yield tmp_path
    packs.clear_cache()


def write_pack(root: Path, pack_id: str, *, maturity: str = "stable", extra: str = "") -> Path:
    directory = root / ".agentfox" / "packs" / pack_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pack.yaml").write_text(
        f"id: {pack_id}\nversion: 0.1.0\nmaturity: {maturity}\nowners: [acme]\n{extra}"
    )
    return directory


def test_the_builtin_packs_all_load(project):
    assert [p.id for p in packs.load_packs()] == BUILTIN_IDS
    assert all(p.origin == "builtin" for p in packs.load_packs())


def test_the_template_is_not_a_pack():
    assert all(not d.name.startswith("_") for d in packs.pack_dirs(packs.BUILTIN_ROOT))


def test_a_project_pack_loads_after_the_builtin_ones(project):
    write_pack(project, "acme/claims")
    loaded = packs.load_packs()
    assert "acme/claims" in [p.id for p in loaded]
    assert packs.get("acme/claims").origin == "project"


def test_only_stable_packs_load_unless_the_setting_says_otherwise(project, monkeypatch):
    write_pack(project, "acme/new", maturity="incubating")
    write_pack(project, "acme/wild", maturity="sandbox")
    assert packs.get("acme/new") is None
    skipped = {p.id: p.skipped for p in packs.discover()}
    assert "maturity incubating" in skipped["acme/new"]

    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("AGENTFOX_PACK_MATURITY", "incubating")
    reset_settings_cache()
    packs.clear_cache()
    ids = [p.id for p in packs.load_packs()]
    assert "acme/new" in ids and "acme/wild" not in ids


def test_a_pack_for_a_newer_core_is_skipped(project):
    write_pack(project, "acme/future", extra='requires_core: ">=99"\n')
    assert packs.get("acme/future") is None
    (future,) = [p for p in packs.discover() if p.id == "acme/future"]
    assert "requires agentfox >=99" in future.skipped


def test_a_project_pack_replaces_a_builtin_one_with_the_same_id(project):
    write_pack(project, "baseline")
    (baseline,) = [p for p in packs.load_packs() if p.id == "baseline"]
    assert baseline.origin == "project"
    assert baseline.replaces and baseline.replaces[0].startswith("builtin:")
    # What is shipped does not change with the working directory.
    assert packs.builtin_pack("baseline").origin == "builtin"


def test_an_unreadable_pack_is_skipped_or_refused_when_strict(project):
    directory = project / ".agentfox" / "packs" / "broken"
    directory.mkdir(parents=True)
    (directory / "pack.yaml").write_text("id: Broken Pack\nversion: x\n")
    assert "Broken Pack" not in [p.id for p in packs.discover()]
    with pytest.raises(PackError):
        packs.discover(strict=True)


def test_an_entry_point_names_a_folder_of_packs(project, monkeypatch, tmp_path_factory):
    installed = tmp_path_factory.mktemp("site") / "packs"
    pack_dir = installed / "acme" / "installed"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "id: acme/installed\nversion: 1.0.0\nmaturity: stable\nowners: [acme]\n"
    )

    class EntryPoint:
        name = "acme"

        def load(self):
            return lambda: installed

    monkeypatch.setattr(packs.loader, "entry_points", lambda group: [EntryPoint()])
    assert packs.get("acme/installed").origin == "installed:acme"


def test_the_manifest_schema_rejects_what_it_should():
    PackManifest.model_validate({"id": "a/b-c", "version": "1.0", "owners": ["x"]})
    for bad in (
        {"id": "A/B", "version": "1.0", "owners": ["x"]},
        {"id": "a", "version": "one", "owners": ["x"]},
        {"id": "a", "version": "1.0", "owners": []},
        {"id": "a", "version": "1.0", "owners": ["x"], "maturity": "beta"},
        {"id": "a", "version": "1.0", "owners": ["x"], "requires_core": "~0.3"},
        {"id": "a", "version": "1.0", "owners": ["x"], "unknown": 1},
    ):
        with pytest.raises(ValueError):
            PackManifest.model_validate(bad)
    schema = PackManifest.model_json_schema()
    assert {"id", "version", "owners"} <= set(schema["required"])


@pytest.mark.parametrize(
    ("spec", "version", "ok"),
    [
        (">=0.3", "0.3.1", True),
        (">=0.4", "0.3.1", False),
        (">=0.3, <1", "0.3.1", True),
        ("==0.3.1", "0.3.1", True),
        ("!=0.3.1", "0.3.1", False),
        ("", "0.3.1", True),
    ],
)
def test_requires_core(spec, version, ok):
    assert core_satisfies(spec, version) is ok


def test_the_fallback_packs_come_from_pack_data():
    assert [p.id for p in packs.fallback_policy_packs(None)] == ["baseline"]
    assert [p.id for p in packs.fallback_policy_packs("High")] == ["baseline", "eu-ai-act"]
    assert [p.id for p in packs.fallback_policy_packs("prohibited")] == ["baseline", "eu-ai-act"]


def test_vocabulary_merges_in_pack_order_first_definition_wins(project):
    write_pack(
        project,
        "zz/extra",
        extra="vocabulary:\n  tool_hints: {refund: other.refund, chargeback: payments.dispute}\n",
    )
    hints = packs.merged_mapping("tool_hints")
    assert hints["refund"] == "payments.refund"
    assert hints["chargeback"] == "payments.dispute"
    assert list(hints)[:3] == ["refund", "transfer", "payment"]


def test_a_pack_check_registers_through_the_decorator(project):
    directory = write_pack(project, "acme/checks")
    (directory / "checks").mkdir()
    (directory / "checks" / "promise.py").write_text(
        "from agentfox.platform.checks import check\n\n\n"
        "@check('acme.promise', surfaces=['output'], order=2000)\n"
        "def promise(ctx):\n"
        "    '''An acme promise.'''\n"
        "    return {}\n"
    )
    packs.reset_checks()
    try:
        assert packs.load_checks() == ["agentfox_pack_checks.acme_checks_promise"]
        (found,) = [c for c in check_registry.checks() if c.key == "acme.promise"]
        assert found.source == "pack:acme/checks"
        assert found.surfaces == frozenset({"output"})
    finally:
        check_registry.unregister("acme.promise")
        packs.reset_checks()


def test_controls_come_from_the_compliance_pack_or_the_override(project, monkeypatch, tmp_path):
    (path,) = packs.control_files("controls.yaml")
    assert path.parts[-4:] == ("compliance", "catalog", "controls", "controls.yaml")

    from agentfox.core.config import reset_settings_cache

    monkeypatch.setenv("AGENTFOX_COMPLIANCE_DIR", str(tmp_path))
    reset_settings_cache()
    assert packs.control_files("controls.yaml") == [tmp_path / "controls.yaml"]
