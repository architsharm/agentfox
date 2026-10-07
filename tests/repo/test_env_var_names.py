"""What the product tells people to set is the current name.

Every setting is read as ``AGENTFOX_<name>`` (core/config.py); the pre-rename
``NOMETRIA_<name>`` is no longer read at all. What went wrong first was the text: some
fifty error messages, hints and generated-file comments still told a new user to set
``NOMETRIA_ALLOW_EGRESS`` or ``NOMETRIA_TOKEN_ENCRYPTION_KEY`` — a name they have no
other reason to know, for a product that is not called that.

So: no string in the package names a ``NOMETRIA_*`` variable, except where the job
is noticing a leftover legacy name, where saying it is the point.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "agentfox"

#: Modules that name the legacy names on purpose and say so.
LEGACY_READERS = {
    "core/config.py",  # notices leftover NOMETRIA_* settings; reads none of them
    "capabilities/detection/detectors/secrets.py",  # a detector label, not a variable
}

#: No module reads x-nometria-* headers any more.
LEGACY_HEADER_READERS: set[str] = set()
LEGACY_HEADER = re.compile(r"x[-_]nometria[-_]", re.I)

LEGACY = re.compile(r"\bNOMETRIA_[A-Z*]")
#: A mention that explicitly calls the old name the old name is fine.
SAYS_LEGACY = re.compile(r"legacy|older|old name|pre-rename|still (read|accepted)", re.I)


def _strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def test_no_user_facing_string_names_a_nometria_variable():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in LEGACY_READERS:
            continue
        for lineno, text in _strings(path):
            for line in text.splitlines():
                if LEGACY.search(line) and not SAYS_LEGACY.search(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    assert offenders == [], "use AGENTFOX_* in text:\n" + "\n".join(offenders)


def test_generated_config_names_the_current_prefix():
    from agentfox.apps.cli.onboarding import _CONFIG_TEMPLATE

    assert "AGENTFOX_*" in _CONFIG_TEMPLATE


def test_no_header_the_package_emits_or_documents_is_x_nometria():
    """Headers are X-AgentFox-*. The old spelling is neither emitted nor accepted."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in LEGACY_HEADER_READERS:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if LEGACY_HEADER.search(line) and not SAYS_LEGACY.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    assert offenders == [], "use X-AgentFox-* headers:\n" + "\n".join(offenders)
