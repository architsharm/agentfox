"""Downloading a public dataset once, for the `fetch_*.py` scripts."""

from __future__ import annotations

import subprocess


def fetch(url: str) -> str:
    """The body at `url`, through curl (follows redirects, fails on an HTTP error)."""
    result = subprocess.run(
        ["curl", "-sL", "--fail", url], capture_output=True, text=True, check=True
    )
    return result.stdout
