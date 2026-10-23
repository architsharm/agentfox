"""Which rules are applied to which agents right now, for the Policies page.

Worked out from each agent's effective policy (`effective_for`), so it is what the
engine would actually run: workspace libraries, rules set for one agent, and an
agent's changes to a workspace rule all count, each where it really applies.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.protection.libraries import BASIC, STARTER, library_of
from agentfox.core.models import Agent, Policy
from agentfox.platform.policy import effective_for
from agentfox.platform.registry.projects import GONE


def applied_rules(session: Session) -> dict[str, Any]:
    """Every rule in force on at least one agent: what it does, where it comes from,
    and whether it applies to every agent or only some.

    Drafts count, marked ``draft``: an agent `agentfox init --key` proposed is a draft
    until a person adds it, and the rules set for it (a library applied to its project,
    say) take effect then. ``agentList`` is every agent counted, so a project whose
    agents are all drafts still shows them."""
    agents = list(
        session.scalars(select(Agent).where(Agent.status.not_in(GONE)).order_by(Agent.name))
    )
    names = {p.key: p.name or p.key for p in session.scalars(select(Policy))}
    rows: dict[str, dict[str, Any]] = {}
    for agent in agents:
        for r in effective_for(session, agent_slug=agent.slug).explain()["rules"]:
            row = rows.setdefault(
                r["rule_id"],
                {
                    "id": r["rule_id"],
                    "description": r.get("description") or "",
                    "effects": Counter(),
                    "enforcing": 0,
                    "agents": [],
                    "libraries": {},
                },
            )
            row["effects"][r["effect"]] += 1
            row["enforcing"] += int(r.get("enforcement") == "enforce")
            row["agents"].append(
                {
                    "slug": agent.slug,
                    "name": agent.name or agent.slug,
                    "draft": agent.status == "draft",
                }
            )
            key = r.get("policy") or ""
            lib = library_of(r["rule_id"], key, r.get("level") or "", names.get(key, ""))
            row["libraries"][lib] = lib

    out = []
    for row in rows.values():
        effect, _n = row["effects"].most_common(1)[0]
        n = len(row["agents"])
        out.append(
            {
                "id": row["id"],
                "description": row["description"],
                "effect": effect,
                # Some agents changed what it does.
                "varies": len(row["effects"]) > 1,
                "mode": "enforce"
                if row["enforcing"] == n
                else ("observe" if not row["enforcing"] else "mixed"),
                "all": n == len(agents),
                "agents": row["agents"],
                "libraries": sorted(row["libraries"].values()),
            }
        )
    out.sort(key=lambda r: (r["mode"] != "enforce", not r["all"], r["libraries"], r["id"]))
    # The two libraries applied per agent: on how many agents each is.
    per_agent = {}
    for lib in (BASIC, STARTER):
        mine = [r for r in out if lib in r["libraries"]]
        on = {a["slug"] for r in mine for a in r["agents"]}
        per_agent[lib] = {
            "rules": len(mine),
            "agents": len(on),
            "blocking": bool(mine) and all(r["mode"] == "enforce" for r in mine),
        }
    return {
        "agents": len(agents),
        "agentList": [
            {
                "slug": a.slug,
                "name": a.name or a.slug,
                "status": a.status,
                "draft": a.status == "draft",
            }
            for a in agents
        ],
        "rules": out,
        "perAgent": per_agent,
    }
