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

from agentfox.core.models import Agent, Policy
from agentfox.platform.policy import effective_for
from agentfox.platform.registry.projects import REMOVED


def applied_rules(session: Session) -> dict[str, Any]:
    """Every rule in force on at least one agent: what it does, where it comes from,
    and whether it applies to every agent or only some."""
    agents = list(
        session.scalars(
            select(Agent)
            .where(Agent.status.not_in(("rejected", "draft", REMOVED)))
            .order_by(Agent.name)
        )
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
            row["agents"].append({"slug": agent.slug, "name": agent.name or agent.slug})
            key = r.get("policy") or ""
            # A workspace library by its name; an agent's own layer is "set for this agent".
            if r.get("level") == "org" and key:
                row["libraries"][key] = names.get(key, key)
            else:
                row["libraries"]["agent"] = "Set for agents"

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
    return {"agents": len(agents), "rules": out}
