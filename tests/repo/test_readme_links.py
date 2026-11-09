"""README.md is also the PyPI project page, where relative links and images break.

PyPI renders the README without the repository around it, so `docs/x.md` and
`<img src="docs/assets/...">` resolve against pypi.org and 404. Every link into the
repository is absolute instead, and has to point at a file that exists, so GitHub
and PyPI both render it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = (REPO_ROOT / "README.md").read_text()

BLOB = "https://github.com/architsharm/agentfox/blob/main/"
TREE = "https://github.com/architsharm/agentfox/tree/main/"
RAW = "https://raw.githubusercontent.com/architsharm/agentfox/main/"

TARGET = re.compile(r'(?:\]\(|src="|href=")([^)"\s]+)')


def _targets() -> list[str]:
    return TARGET.findall(README)


def test_readme_has_no_relative_links() -> None:
    relative = [u for u in _targets() if not u.startswith(("http://", "https://", "mailto:", "#"))]
    assert not relative, f"Relative README links break on PyPI; make them absolute: {relative}"


def test_absolute_repo_links_point_at_real_files() -> None:
    missing = []
    for url in _targets():
        for prefix in (BLOB, TREE, RAW):
            if url.startswith(prefix):
                path = url[len(prefix) :].split("#", 1)[0]
                if not (REPO_ROOT / path).exists():
                    missing.append(url)
    assert not missing, f"README links to repository paths that do not exist: {missing}"


def test_images_use_raw_urls() -> None:
    images = re.findall(r'<img[^>]*src="([^"]+)"', README) + re.findall(
        r"!\[[^\]]*\]\(([^)]+)\)", README
    )
    wrong = [u for u in images if u.startswith(BLOB)]
    assert not wrong, f"Images through github.com/blob do not render on PyPI; use {RAW}: {wrong}"


def test_site_docs_links_land_on_a_real_page() -> None:
    """`/docs/guides/...` only redirects (and `/docs/guides/monitoring` landed on a page
    that did not mention monitoring); README links name the page itself."""
    docs = REPO_ROOT / "dashboard" / "app" / "docs"
    missing = []
    for url in _targets():
        if url.startswith("https://useagentfox.com/docs"):
            path = url[len("https://useagentfox.com/docs") :].split("#", 1)[0].strip("/")
            if not (docs / path / "page.tsx").is_file():
                missing.append(url)
    assert not missing, f"README links to docs pages that do not exist: {missing}"
