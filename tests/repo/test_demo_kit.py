"""The deployed demo's copy of the shared demo kit must not drift from the original.

`demo/kit/` is the one implementation both red-team demos use. The LangChain demo
deploys on Vercel with `demo/redteam-live-lang` as its Root Directory, so it carries a
committed copy at `demo/redteam-live-lang/kit/`; an edit to one without the other
would ship different code than the CrewAI demo and the docs describe
(scripts/check/demo_kit.py).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts" / "check" / "demo_kit.py"


def test_deployed_demo_kit_copy_matches_demo_kit():
    result = subprocess.run(
        [sys.executable, str(CHECKER)], cwd=REPO, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_demo_folders_hold_no_forked_kit_code():
    """The adapters stay thin: the kit's dataset and toolkit body live only in the kit."""
    for demo in ("redteam-live", "redteam-live-lang"):
        text = (REPO / "demo" / demo / "support_tools.py").read_text(encoding="utf-8")
        assert "from kit.support_tools import" in text, demo
        assert "ORDERS: dict" not in text and "def _render" not in text, demo
