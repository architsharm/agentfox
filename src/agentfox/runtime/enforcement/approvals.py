"""What a held call looks like to the person deciding it, and how a retry redeems it.

An approval is filed whenever a decision escalates. For a tool call the
person sees the tool and its arguments. A held *message* (an input, an output, an
agent-to-agent message) has no tool, and ``tool: null`` with empty arguments would
leave the approver nothing to decide on. So it is filed as
``message:<surface>`` with the content (detected PII and secrets masked) and the
content's digest, which is what a retry is matched against.
"""

from __future__ import annotations

from typing import Any

from agentfox.capabilities.detection import redact_content
from agentfox.platform.identity.service import content_digest

#: How much of a held message the approval shows. The digest binds the whole of it.
EXCERPT_CHARS = 2000


def held_call(
    *,
    surface: str,
    tool_key: str | None,
    arguments: dict[str, Any] | None,
    content: str,
    detections: list[Any] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """The (tool, arguments) an approval for this decision is filed under and bound to."""
    if tool_key:
        return tool_key, dict(arguments or {})
    sensitive = [d for d in detections or [] if str(d.entity_type).startswith(("PII", "SECRET"))]
    excerpt = redact_content(content, sensitive, mode="mask") if sensitive else content
    if len(excerpt) > EXCERPT_CHARS:
        excerpt = excerpt[:EXCERPT_CHARS] + "…"
    return f"message:{surface}", {
        "surface": surface,
        "content": excerpt,
        "content_sha256": content_digest(content),
    }


#: How strongly a fired rule's effect asks for the call to stop, for ordering reasons.
_STOPS = {"block": 3, "escalate": 2, "verify": 1}

#: Appended to a watching rule's reason: it was recorded, not what held the call.
WATCHING_NOTE = "(watching only)"


def approval_reason(rules_fired: list[dict[str, Any]]) -> str:
    """Why a call was held, the rule that actually held it first.

    The decision's reason joins every fired rule in the order they ran, so a call held
    by an enforced approval limit was filed under whichever rule happened to run first,
    often one that was only watching ("EU AI Act Art. 14 …"), and the Approvals page
    shows the first sentence. Here the enforcing rules come first, strongest effect
    first, and a watching rule is labelled as such: it is context, not the cause.
    Rules that allow add nothing to why a call is held and are left out."""
    seen: set[str] = set()
    ranked: list[tuple[int, int, str]] = []
    for rule in rules_fired or []:
        text = " ".join(str(rule.get("reason") or "").split()).rstrip(";").strip()
        effect = str(rule.get("effect") or "")
        if not text or effect == "allow" or text in seen:
            continue
        seen.add(text)
        watching = rule.get("mode") == "observe"
        if watching:
            text = f"{text.rstrip('.')} {WATCHING_NOTE}."
        ranked.append((int(watching), -_STOPS.get(effect, 0), text))
    # A stable sort: rules of the same standing keep the order they ran in.
    ranked.sort(key=lambda r: (r[0], r[1]))
    return "; ".join(text for _w, _s, text in ranked)
