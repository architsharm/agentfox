"""The docs site's generated reference is current, and every command it prints runs.

scripts/docs_reference.py renders the CLI and HTTP reference into
dashboard/lib/reference/*.json from the live code, and resolves every `agentfox ...`
inside a code block under dashboard/app/docs against the click tree. A renamed
command or a removed flag fails here instead of on the website.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_the_docs_reference_is_current_and_every_documented_command_exists():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "docs_reference.py"), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
