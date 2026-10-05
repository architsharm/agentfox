"""Compatibility shim: the package is now ``agentfox``.

Nometria was renamed to AgentFox. The website, the CLI and the documentation all say
``agentfox``, but ``import nometria``, ``nometria.auto()`` and
``from nometria.integrations.langgraph import ...`` were the documented entry points
until that rename, so anyone who followed the docs before it has one of those lines
in their own code. Breaking them on upgrade turns a rename into an outage in someone
else's process, which is not a trade this project gets to make for them.

Every ``nometria`` name resolves to the identical ``agentfox`` module object, not to
a second copy loaded under a different name. That distinction is the whole point of
the finder below: two copies would mean two settings caches and two audit-chain
states, which is a real bug rather than a cosmetic one.

Deprecated. It warns once on first import and will be removed in a future release.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from importlib.abc import MetaPathFinder

import agentfox as _agentfox

_OLD = "nometria"
_NEW = "agentfox"


class _RenamedPackageFinder(MetaPathFinder):
    """Resolve ``nometria.x.y`` to the already-imported ``agentfox.x.y``.

    Swapping ``sys.modules["nometria"]`` alone is not enough: it redirects
    ``import nometria`` but leaves ``from nometria.config import x`` to load
    ``src/agentfox/core/config.py`` a second time under the name ``nometria.config``,
    producing a distinct module with its own module-level state.
    """

    def find_spec(self, fullname: str, path=None, target=None):  # noqa: ANN001, ANN202
        if fullname != _OLD and not fullname.startswith(f"{_OLD}."):
            return None
        renamed = _NEW + fullname[len(_OLD) :]
        module = importlib.import_module(renamed)
        # Registering under both names is what makes the two spellings the same
        # object. The import machinery then finds it in sys.modules and does not
        # execute anything further.
        sys.modules[fullname] = module
        return module.__spec__


if not any(isinstance(f, _RenamedPackageFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _RenamedPackageFinder())

warnings.warn(
    "The `nometria` package has been renamed to `agentfox`. Import `agentfox` "
    "instead; `import nometria` will stop working in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _agentfox
