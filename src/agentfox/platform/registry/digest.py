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
from agentfox.platform.registry.service import tool_input_schema

#: The MCP tool annotations that describe what a call does to the world. A client that
#: auto-approves read-only tools reads exactly these, so a change to one is held like a
#: change to the description. `title` and `outputSchema` are not pinned: the title is a
#: display label, and the result is evaluated and tainted as ``tool_result`` whatever
#: shape it claims. A change to either still raises a ``schema_drift`` finding.
IMPACT_ANNOTATIONS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def impact_annotations(descriptor: dict[str, Any]) -> dict[str, Any]:
    annotations = descriptor.get("annotations") or {}
    if not isinstance(annotations, dict):
        return {}
    return {k: annotations[k] for k in IMPACT_ANNOTATIONS if k in annotations}


def tool_digest(descriptor: dict[str, Any], *, annotations: bool = True) -> str:
    """Digest the parts of a tool descriptor that change its meaning.

    Name, description, input schema and the impact annotations — the description is
    included deliberately, because tool-poisoning attacks change *only* the
    description and leave the schema identical. Annotations enter the material only
    when there are some, so a tool without them digests as it always did.
    ``annotations=False`` compares against a record made before they were kept.
    """
    material: dict[str, Any] = {
        "name": descriptor.get("name"),
        "description": descriptor.get("description", ""),
        "inputSchema": descriptor.get("inputSchema", descriptor.get("input_schema", {})),
    }
    hints = impact_annotations(descriptor) if annotations else {}
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
