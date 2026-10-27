"""The digest that pins a tool's meaning: what an MCP listing is compared against.

The governor pins each registered tool to a digest of its name, description, input
schema and impact annotations; a listing that digests differently is held as a
change. The appliers that accept such a change compare records in the same terms,
so the digest lives here, below both of them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agentfox.core.models import Tool
from agentfox.platform.registry.service import _MARKER_KEYS, tool_input_schema

#: The MCP tool annotations that describe what a call does to the world. A client that
#: auto-approves read-only tools reads exactly these, so a change to one is held like a
#: change to the description. `title` and `outputSchema` are not pinned: the title is a
#: display label, and the result is evaluated and tainted as ``tool_result`` whatever
#: shape it claims. A change to either still raises a ``schema_drift`` finding.
IMPACT_ANNOTATIONS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def impact_annotations(descriptor: dict[str, Any]) -> dict[str, Any]:
    """The impact hints a descriptor sets. A hint given as null is a hint not given:
    the protocol reads both as its default."""
    annotations = descriptor.get("annotations") or {}
    if not isinstance(annotations, dict):
        return {}
    return {
        k: annotations[k]
        for k in IMPACT_ANNOTATIONS
        if k in annotations and annotations[k] is not None
    }


def listed_definition(descriptor: dict[str, Any]) -> dict[str, Any]:
    """The pinned parts of a listed tool, in the one form they are recorded and digested in.

    Every path that reads a listing — registering it, filing a change to it, accepting
    that change, checking a call against it — goes through this, so a listing cannot
    record one way and digest another. github-mcp-server v0.24.0 listed ``get_me`` with
    ``"inputSchema": null``: the registry stored ``{}`` while the call-time digest took
    the raw null, and the tool was refused as drifted from its first call, accepted or
    not. JSON null, a missing field and the empty value are the same here — they say
    the same thing to a client — and nothing else is folded: any other change to the
    description, schema or impact hints still digests differently. The registry's own
    ``x-agentfox-*`` markers are dropped from a listed schema, as they are from the
    record: they are the operator's statements, never the server's.
    """
    description = descriptor.get("description")
    schema = descriptor.get("inputSchema") or descriptor.get("input_schema") or {}
    if isinstance(schema, dict):
        schema = {k: v for k, v in schema.items() if k not in _MARKER_KEYS}
    return {
        "name": descriptor.get("name"),
        "description": "" if description is None else str(description),
        "inputSchema": schema,
        "annotations": impact_annotations(descriptor),
    }


def tool_digest(descriptor: dict[str, Any], *, annotations: bool = True) -> str:
    """Digest the parts of a tool descriptor that change its meaning.

    Name, description, input schema and the impact annotations, read through
    `listed_definition` — the description is included deliberately, because
    tool-poisoning attacks change *only* the description and leave the schema
    identical. Annotations enter the material only when there are some, so a tool
    without them digests as it always did. ``annotations=False`` compares against a
    record made before they were kept.
    """
    definition = listed_definition(descriptor)
    material: dict[str, Any] = {
        "name": definition["name"],
        "description": definition["description"],
        "inputSchema": definition["inputSchema"],
    }
    hints = definition["annotations"] if annotations else {}
    if hints:
        material["annotations"] = hints
    encoded = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()[:32]


def record_digest(tool: Tool) -> str:
    """The digest of a registered tool, in the same terms as `tool_digest`."""
    return tool_digest(
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool_input_schema(tool),
            "annotations": tool.annotations_json or {},
        }
    )
