"""Shared CLI presentation constants.

``SEVERITY_COLOUR`` was hand-rolled at six call sites across the CLI, one of them
(``business_cli.py``) missing the ``high`` -> ``red`` entry entirely and silently
falling through to the ``dim`` default — a real severity underrepresented in the
one place nobody was cross-checking it against the others. This is the one copy.
"""

from __future__ import annotations

from typing import Any

SEVERITY_COLOUR = {
    "critical": "red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    "info": "dim",
}


#: How many trailing characters of an id are shown in a table. Ids here are
#: time-ordered, so everything created in the same second shares a *leading* prefix
#: and differs only at the tail — an abbreviation that keeps the head would print the
#: same string on every row.
ID_TAIL = 8


def short_id(value: str, tail: int = ID_TAIL) -> str:
    """An id short enough for a table column and still unique on the eye."""
    if not value or len(value) <= tail:
        return value or "—"
    return f"…{value[-tail:]}"


def match_id(value: str, candidate: str) -> bool:
    """True when what the user typed names this id: the whole thing, or the tail as
    printed in a table (with or without the leading ellipsis)."""
    typed = (value or "").lstrip("…").strip()
    if not typed:
        return False
    return candidate == value or candidate.endswith(typed)


def print_unknown_agent(console: Any, session: Any, slug: str) -> None:
    """Report a slug that is not an agent, and name the ones that are.

    `capability_cli` did this and `controls_cli` did not, so whether a typo told
    you the answer depended on which command you had typed. Naming the options is
    the house style — `policy enforce` lists its policies on the same mistake —
    and a slug is exactly the argument nobody remembers exactly.
    """
    from sqlalchemy import select

    from ..models import Agent

    known = sorted(a.slug for a in session.scalars(select(Agent)))
    console.print(f"[red]unknown agent '{slug}'[/]")
    if known:
        console.print(f"  known agents: {', '.join(known)}")
    else:
        console.print("  no agents registered yet — run `agentfox seed` or register one.")
