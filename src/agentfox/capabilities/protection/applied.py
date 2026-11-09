"""Which rules are applied to which agents right now, for the Policies page.

Worked out from each agent's effective policy (`effective_for`), so it is what the
engine would actually run: workspace libraries, rules set for one agent, and an
agent's changes to a workspace rule all count, each where it really applies. So do
the two things the enforcer applies without a binding: the shipped fallback when
nothing is bound for an agent, and its own containment facts (a missing grant, a
composed escalation), listed under Tool containment in that library's mode.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.protection.libraries import BASIC, STARTER, library_of, library_titles
from agentfox.core.models import Agent, Policy
from agentfox.platform.policy import (
    containment_mode,
    effective_for,
    fallback_policies,
    policies_in_force,
    runtime_environment,
)
from agentfox.platform.registry.projects import GONE

#: The pack whose library the enforcer's own containment facts belong to.
CONTAINMENT_POLICY = "tool-containment"

#: The containment facts the enforcer adds itself, beside any pack rule: each blocks
#: while Tool containment blocks and is recorded as would-block while it watches
#: (`platform.policy.containment_mode`). A pack rule of the same meaning
#: (`capability.denied`) stands in for the first when it is in force.
BUILT_IN = (
    (
        "capability.default_deny",
        "A tool the agent was not granted is refused.",
        "capability.denied",
    ),
    (
        "composition.escalation",
        "A value a lower-impact tool returned is used by a tool that changes more.",
        None,
    ),
)


def _in_force(session: Session, agent: Agent) -> list[dict[str, Any]]:
    """What the enforcer evaluates for this agent, rule by rule, in the shape of
    `EffectivePolicy.explain()["rules"]`: its packs in force (in the environment
    the runtime resolves it in), else the shipped fallback the enforcer applies
    when nothing is bound, and the containment facts it adds itself."""
    environment = runtime_environment(session, agent.slug)
    effective = effective_for(session, agent_slug=agent.slug, environment=environment).explain()
    rules = list(effective["rules"])
    skipped: list[Any] = []
    bound = policies_in_force(session, agent.slug, environment, skipped=skipped)
    if not bound and not skipped:
        # `Enforcer._evaluate_policies`: nothing bound is not nothing checked.
        bound = [
            (doc, None, None)
            for doc in fallback_policies(agent.risk_tier)
            if doc.matches_scope(agent.slug, environment)
        ]
        rules += [
            {
                "rule_id": rule.id,
                "description": rule.description or "",
                "effect": rule.effect,
                "enforcement": "observe",
                "policy": doc.key,
                "level": "org",
            }
            for doc, _v, _b in bound
            for rule in doc.rules
            if rule.enabled
        ]
    mode = containment_mode(bound)
    present = {r["rule_id"] for r in rules}
    for rule_id, description, stood_in_by in BUILT_IN:
        if rule_id in present or (stood_in_by and stood_in_by in present):
            continue
        rules.append(
            {
                "rule_id": rule_id,
                "description": description,
                "effect": "block",
                "enforcement": mode,
                "policy": CONTAINMENT_POLICY,
                "level": "org",
                "built_in": True,
            }
        )
    return rules


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
        for r in _in_force(session, agent):
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
            if r.get("built_in"):
                lib = library_titles().get(CONTAINMENT_POLICY, lib)
                row["built_in"] = True
            row["libraries"][lib] = lib

    # Business rules (an approval limit written in New rule, a library's ladders) are
    # stored apart from the packs but are rules in force all the same: on the agent
    # they are limited to, or on every agent.
    from agentfox.capabilities.business.store import rule_entries

    for entry in rule_entries(session):
        on = [a for a in agents if entry["agent"] in (None, a.slug)]
        if not on:
            continue
        rows[entry["rule_id"]] = {
            "id": entry["rule_id"],
            "description": entry["description"] or entry["title"],
            "effects": Counter({entry["effect"]: len(on)}),
            "enforcing": len(on) if entry["enforcement"] == "enforce" else 0,
            "agents": [
                {"slug": a.slug, "name": a.name or a.slug, "draft": a.status == "draft"} for a in on
            ],
            "libraries": {entry["library"]: entry["library"]},
        }

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
                # Added by the enforcer itself, not by a rule someone can open.
                "builtIn": bool(row.get("built_in")),
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
