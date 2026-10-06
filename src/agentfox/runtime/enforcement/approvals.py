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

from agentfox.detection import redact_content
from agentfox.identity.service import content_digest

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
