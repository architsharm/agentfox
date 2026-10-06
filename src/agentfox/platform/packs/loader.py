"""Finding, reading and choosing capability packs.

Packs come from three places, read in this order:

1. **built in** — ``src/agentfox/packs/`` (shipped in the wheel);
2. **installed** — the ``agentfox.packs`` entry-point group, for ``agentfox-pack-*``
   packages; an entry point names a directory (or a callable returning one) that is
   either a pack or a folder of packs;
3. **project** — ``<project>/.agentfox/packs/``, beside ``agentfox.toml``, so a team's
   packs travel with its repository.

A pack is any directory holding a ``pack.yaml``; a directory whose name starts with
``_`` or ``.`` (the scaffolding template) is never a pack. A pack with the same id as
one read earlier replaces it, the way a project policy file replaces a shipped one.

Only ``stable`` packs load unless the `pack_maturity` setting says otherwise, and a
pack whose ``requires_core`` this version does not meet is skipped. `discover` returns
everything with the reason a pack is not loaded; `load_packs` returns what loads.

This module returns paths and parsed manifests only. What a pack's files mean is up to
whoever reads them: the policy store reads ``policies/``, the compliance catalog
``controls/``, the red team ``probes/``, the check registry ``checks/``.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import yaml

from agentfox.platform.packs.model import MATURITIES, PackManifest, core_satisfies

log = logging.getLogger(__name__)

#: The packs shipped inside the package.
BUILTIN_ROOT = Path(__file__).resolve().parents[2] / "packs"
#: Where a project keeps packs of its own, relative to its root (the working directory).
PROJECT_PACK_DIR = Path(".agentfox") / "packs"
#: The entry-point group an installed pack package registers under.
ENTRY_POINT_GROUP = "agentfox.packs"

ORIGIN_BUILTIN = "builtin"
ORIGIN_PROJECT = "project"


class PackError(RuntimeError):
    """A pack on disk could not be read, named by its directory."""

    def __init__(self, path: Path, cause: Exception | str) -> None:
        detail = " ".join(str(cause).split())
        super().__init__(f"{path}: {detail}")
        self.path = path
        self.cause = cause


@dataclass(frozen=True)
class Pack:
    """One pack: its manifest, where it is, and where it came from."""

    manifest: PackManifest
    root: Path
    origin: str
    #: Why it does not load, or "" when it does. Set by `discover`.
    skipped: str = ""
    #: Packs this one replaced (same id, read earlier), as ``origin:path``.
    replaces: tuple[str, ...] = field(default=())

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def maturity(self) -> str:
        return self.manifest.maturity

    def files(self, folder: str, pattern: str = "*.y*ml") -> list[Path]:
        """The files in one of the pack's folders, sorted by name."""
        directory = self.root / folder
        if not directory.is_dir():
            return []
        return sorted(p for p in directory.glob(pattern) if p.is_file())

    def file(self, folder: str, name: str) -> Path | None:
        path = self.root / folder / name
        return path if path.is_file() else None

    def fixture(self, name: str) -> Any:
        """``fixtures/<name>.yaml``, parsed; None if the pack has no such fixture."""
        path = self.file("fixtures", f"{name}.yaml")
        return yaml.safe_load(path.read_text()) if path else None

    @property
    def readme(self) -> Path | None:
        path = self.root / "README.md"
        return path if path.is_file() else None

    def contents(self) -> dict[str, list[str]]:
        """Which folders the pack has and the files in each, for `packs show`."""
        out: dict[str, list[str]] = {}
        for folder in ("policies", "controls", "ladders", "probes", "cases", "fixtures"):
            names = [p.name for p in self.files(folder)]
            if names:
                out[folder] = names
        checks = [p.name for p in self.files("checks", "*.py")]
        if checks:
            out["checks"] = checks
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.manifest.version,
            "maturity": self.maturity,
            "title": self.manifest.title,
            "origin": self.origin,
            "path": str(self.root),
            "owners": list(self.manifest.owners),
            "tags": list(self.manifest.tags),
            "loaded": not self.skipped,
            "skipped": self.skipped,
            "replaces": list(self.replaces),
            "contents": self.contents(),
        }


def read_pack(directory: Path, origin: str) -> Pack:
    """Read and validate ``directory/pack.yaml``."""
    path = directory / "pack.yaml"
    try:
        data = yaml.safe_load(path.read_text()) or {}
        manifest = PackManifest.model_validate(data)
    except Exception as exc:
        raise PackError(directory, exc) from exc
    return Pack(manifest=manifest, root=directory.resolve(), origin=origin)


def pack_dirs(root: Path) -> list[Path]:
    """Every pack directory under ``root`` (``root`` itself if it is one), sorted."""
    if not root.is_dir():
        return []
    if (root / "pack.yaml").is_file():
        return [root]
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith(("_", ".")):
            found.extend(pack_dirs(child))
    return found


def project_pack_dir(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / PROJECT_PACK_DIR


def _entry_point_roots() -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    try:
        found = list(entry_points(group=ENTRY_POINT_GROUP))
    except Exception:  # pragma: no cover - a broken environment
        return roots
    for ep in found:
        try:
            target = ep.load()
            target = target() if callable(target) else target
            roots.append((f"installed:{ep.name}", Path(str(target))))
        except Exception:
            log.warning("pack entry point %s could not be loaded", ep.name, exc_info=True)
    return roots


def _sources(root: Path | None) -> list[tuple[str, Path]]:
    return [
        (ORIGIN_BUILTIN, BUILTIN_ROOT),
        *_entry_point_roots(),
        (ORIGIN_PROJECT, project_pack_dir(root)),
    ]


def _maturity_setting() -> str:
    from agentfox.core.config import get_settings

    value = str(getattr(get_settings(), "pack_maturity", "stable") or "stable")
    return value if value in MATURITIES else "stable"


def _core_version() -> str:
    from agentfox import __version__

    return __version__


def discover(
    root: Path | None = None,
    *,
    maturity: str | None = None,
    strict: bool = False,
) -> list[Pack]:
    """Every pack from every source, sorted by id, each marked loaded or skipped.

    A pack that cannot be read is logged and left out, unless ``strict``, when it
    raises `PackError` (what `packs validate` wants).
    """
    level = MATURITIES.index(maturity or _maturity_setting())
    version = _core_version()
    by_id: dict[str, Pack] = {}
    for origin, source in _sources(root):
        for directory in pack_dirs(source):
            try:
                pack = read_pack(directory, origin)
            except PackError:
                if strict:
                    raise
                log.warning("capability pack at %s could not be read", directory, exc_info=True)
                continue
            skipped = ""
            if MATURITIES.index(pack.maturity) > level:
                skipped = f"maturity {pack.maturity} (loading {MATURITIES[level]} and above)"
            elif pack.manifest.requires_core and not core_satisfies(
                pack.manifest.requires_core, version
            ):
                skipped = f"requires agentfox {pack.manifest.requires_core}; this is {version}"
            replaced = by_id.get(pack.id)
            replaces = (
                (*replaced.replaces, f"{replaced.origin}:{replaced.root}") if replaced else ()
            )
            by_id[pack.id] = Pack(
                manifest=pack.manifest,
                root=pack.root,
                origin=origin,
                skipped=skipped,
                replaces=replaces,
            )
    return [by_id[key] for key in sorted(by_id)]


_cache: dict[tuple[str, str], tuple[Pack, ...]] = {}


def load_packs(root: Path | None = None, *, maturity: str | None = None) -> list[Pack]:
    """The packs that load in this process, sorted by id. Cached per project root."""
    key = (str((root or Path.cwd()).resolve()), maturity or _maturity_setting())
    cached = _cache.get(key)
    if cached is None:
        cached = tuple(p for p in discover(root, maturity=maturity) if not p.skipped)
        _cache[key] = cached
    return list(cached)


def clear_cache() -> None:
    """Forget what was discovered (tests that write packs, or a reload)."""
    _cache.clear()
    _builtin_cache.clear()


_builtin_cache: dict[str, tuple[Pack, ...]] = {}


def builtin_packs() -> list[Pack]:
    """The packs shipped in the package, whatever their maturity, sorted by id.

    For the paths that must not depend on the working directory or the environment:
    the fallback policies of an unconfigured deployment, the demo world.
    """
    cached = _builtin_cache.get("all")
    if cached is None:
        cached = tuple(read_pack(d, ORIGIN_BUILTIN) for d in pack_dirs(BUILTIN_ROOT))
        cached = tuple(sorted(cached, key=lambda p: p.id))
        _builtin_cache["all"] = cached
    return list(cached)


def _loads(pack: Pack, maturity: str) -> bool:
    if MATURITIES.index(pack.maturity) > MATURITIES.index(maturity):
        return False
    requires = pack.manifest.requires_core
    return not requires or core_satisfies(requires, _core_version())


def shipped_packs(*, maturity: str | None = None) -> list[Pack]:
    """The built-in packs that load at this maturity, whatever else is installed.

    "Shipped" never depends on the project or the environment, so this is what the
    shipped policies, the fallback for an unconfigured deployment and the demo world
    read.
    """
    level = maturity or _maturity_setting()
    return [pack for pack in builtin_packs() if _loads(pack, level)]


def builtin_pack(pack_id: str) -> Pack:
    for pack in builtin_packs():
        if pack.id == pack_id:
            return pack
    raise KeyError(f"no built-in pack {pack_id!r}")


def get(pack_id: str, root: Path | None = None) -> Pack | None:
    """The loaded pack with this id, if any."""
    return next((p for p in load_packs(root) if p.id == pack_id), None)


def vocabulary(key: str, packs: Iterable[Pack] | None = None) -> list[tuple[Pack, Any]]:
    """Each loaded pack's ``vocabulary[key]``, in pack order, where it has one."""
    return [
        (pack, pack.manifest.vocabulary[key])
        for pack in (load_packs() if packs is None else packs)
        if key in pack.manifest.vocabulary
    ]


def merged_mapping(key: str, packs: Iterable[Pack] | None = None) -> dict[str, Any]:
    """``vocabulary[key]`` mappings merged in pack order; the first pack to define a word wins."""
    merged: dict[str, Any] = {}
    for _pack, mapping in vocabulary(key, packs):
        for word, value in (mapping or {}).items():
            merged.setdefault(word, value)
    return merged


def condition_values(field_name: str) -> tuple[str, ...]:
    """The values packs declare a policy condition field may take (in pack order)."""
    values: list[str] = []
    for _pack, mapping in vocabulary("condition_values"):
        for value in (mapping or {}).get(field_name) or []:
            if value not in values:
                values.append(str(value))
    return tuple(values)


def fallback_policy_packs(risk_tier: str | None) -> list[Pack]:
    """The built-in packs whose policies protect an unconfigured deployment at this tier."""
    tier = (risk_tier or "").lower()
    chosen = [
        pack
        for pack in shipped_packs()
        if pack.manifest.fallback is not None
        and ("*" in pack.manifest.fallback.risk_tiers or tier in pack.manifest.fallback.risk_tiers)
    ]
    return sorted(chosen, key=lambda p: (p.manifest.fallback.order, p.id))  # type: ignore[union-attr]


def control_files(name: str, directory: Path | None = None) -> list[Path]:
    """Every ``controls/<name>`` the compliance catalog is read from, in pack order.

    ``directory`` (or the `compliance_dir` setting) replaces the packs with one
    directory; otherwise each loaded pack that ships ``controls/<name>`` contributes it.
    The paths returned when nothing ships the file are empty, and callers say so.
    """
    from agentfox.core.config import get_settings

    override = directory or get_settings().compliance_dir
    if override is not None:
        return [Path(override) / name]
    return [path for pack in load_packs() if (path := pack.file("controls", name))]


_imported_checks: set[str] = set()


def load_checks(packs: Iterable[Pack] | None = None) -> list[str]:
    """Import every loaded pack's ``checks/*.py``, registering its checks. Once each.

    Returns the module names imported by this call.
    """
    from agentfox.platform import checks as registry

    imported: list[str] = []
    for pack in load_packs() if packs is None else packs:
        for path in pack.files("checks", "*.py"):
            if path.name.startswith("_"):
                continue
            name = "agentfox_pack_checks." + "_".join(
                [*pack.id.replace("-", "_").split("/"), path.stem]
            )
            if str(path) in _imported_checks:
                continue
            _imported_checks.add(str(path))

            def _load(path: Path = path, name: str = name) -> None:
                spec = importlib.util.spec_from_file_location(name, path)
                if spec is None or spec.loader is None:
                    raise PackError(path, "not an importable Python file")
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)

            try:
                registry.import_as(f"pack:{pack.id}", _load)
                imported.append(name)
            except Exception:
                log.warning("checks in %s could not be loaded", path, exc_info=True)
    return imported


def reset_checks() -> None:
    """Forget which pack check files were imported (tests)."""
    _imported_checks.clear()


__all__ = [
    "BUILTIN_ROOT",
    "ENTRY_POINT_GROUP",
    "ORIGIN_BUILTIN",
    "ORIGIN_PROJECT",
    "PROJECT_PACK_DIR",
    "Pack",
    "PackError",
    "builtin_pack",
    "builtin_packs",
    "shipped_packs",
    "clear_cache",
    "condition_values",
    "control_files",
    "discover",
    "fallback_policy_packs",
    "get",
    "load_checks",
    "load_packs",
    "merged_mapping",
    "pack_dirs",
    "project_pack_dir",
    "read_pack",
    "reset_checks",
    "vocabulary",
]
