"""Import agent-governance policies: rule YAML and policy manifests.

The translation itself is pure and lives with the policy model
(`platform/policy/compat/agent_governance.py`). This module is the half that knows
about the workspace: it checks each text pattern the way a hand-written custom rule
is checked, lints the result with the policy linter, and applies a plan through the
same stores a hand-made change uses —

* text patterns through `save_rules`: one version of the `custom` pack, each rule
  only *detecting* (effect allow), so it is the imported policy that decides;
* each policy document through `save_policy`, bound in **observe**. A policy that
  is already live keeps its binding and mode; the new version waits for a
  promotion, which needs a recorded simulation to enforce, as always.

Nothing is applied that the plan did not show, and nothing untranslatable is
applied in some weaker form.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from agentfox.capabilities.detection.custom import CustomRuleSpec
from agentfox.capabilities.detection.custom_store import RuleSeed, save_rules
from agentfox.platform.ledger import chain
from agentfox.platform.policy import current_binding, lint_documents, lint_summary, save_policy
from agentfox.platform.policy.compat.agent_governance import (
    TextPattern,
    Translation,
    translate,
)

TOOL = "agent-governance"
MAX_FILES = 200
MAX_TOTAL_CHARS = 2_000_000


def _spec(pattern: TextPattern) -> CustomRuleSpec:
    return CustomRuleSpec(
        key=pattern.key,
        name=pattern.name,
        kind="patterns",
        entries=[pattern.pattern],
        surfaces=pattern.surfaces,
        case_sensitive=pattern.case_sensitive,
        description="Imported with an agent-governance policy; the imported policy decides.",
    )


def plan(source: str, files: dict[str, str] | None = None) -> Translation:
    """Translate, then hold every text pattern to the custom-rule checks."""
    out = translate(source, files or {})
    by_key = {p.key: p for p in out.patterns}
    for item in out.items:
        for key in list(item.patterns):
            pattern = by_key.get(key)
            if pattern is None:
                continue
            try:
                _spec(pattern)
            except ValidationError as exc:
                problem = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
                out.reject(item, f"its pattern `{pattern.pattern[:80]}` is refused here: {problem}")
                break
    return out


def plan_json(out: Translation) -> dict[str, Any]:
    payload = out.to_json()
    payload["tool"] = TOOL
    payload["lint"] = lint_summary(lint_documents(out.documents))
    return payload


def _without_skipped(out: Translation, skip: set[int]) -> list[dict[str, Any]]:
    left_out = []
    drop: set[str] = set()
    for index, item in enumerate(out.items):
        if index in skip and item.skippable and item.status != "untranslatable":
            drop.update(item.rules)
            left_out.append(item.to_json())
    if drop:
        out.drop_rules(drop)
    return left_out


def apply(
    session: Session, out: Translation, *, actor: str, skip: list[int] | None = None
) -> dict[str, Any]:
    """Save a plan: patterns into the custom pack, each policy in observe."""
    left_out = _without_skipped(out, set(skip or []))
    reason = f"imported from {TOOL}"

    sync = None
    if out.patterns:
        seeds = [(_spec(p), RuleSeed(effect="allow")) for p in out.patterns]
        sync = save_rules(session, seeds, actor=actor, reason=reason)[1]

    saved = []
    for doc in out.documents:
        if not doc.rules:
            continue
        policy, version = save_policy(
            session,
            doc.model_copy(update={"mode": "observe"}),
            author=actor,
            notes=reason,
            bind_mode="observe",
            rebind=False,
        )
        binding, live = current_binding(session, policy.id)
        chain.append(
            session,
            "policy.imported",
            actor_type="user",
            actor_id=actor,
            subject_type="policy_version",
            subject_id=version.id,
            payload={
                "policy": policy.key,
                "version": version.version,
                "source": TOOL,
                "rules": len(doc.rules),
                "untranslatable": len(out.untranslatable()),
            },
        )
        saved.append(
            {
                "key": policy.key,
                "version": version.version,
                "live_version": live.version if live else None,
                "mode": binding.mode if binding else None,
                "rules": len(doc.rules),
            }
        )

    return {
        "tool": TOOL,
        "policies": saved,
        "patterns": [p.key for p in out.patterns],
        "custom_policy": {"version": sync.version, "mode": sync.mode} if sync else None,
        "untranslatable": [i.to_json() for i in out.untranslatable()],
        "left_out": left_out,
        "default_action": [d.to_json() for d in out.defaults],
        "unmatched_pass": any(d.unmatched_pass for d in out.defaults),
    }


__all__ = ["MAX_FILES", "MAX_TOTAL_CHARS", "TOOL", "apply", "plan", "plan_json"]
