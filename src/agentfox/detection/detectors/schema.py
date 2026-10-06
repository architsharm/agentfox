"""Output schema/contract enforcement (NOM-RTG-07).

A dependency-free JSON Schema subset validator: types, required, enum, ranges,
patterns, array bounds, nested objects. Enough to cover the contracts agents
actually declare, without pulling `jsonschema` onto the critical path.

Guardrails AI (Apache-2.0 core) is the richer wrapped alternative — see
``adapters/guardrails_ai.py``. Note: the core is Apache-2.0 but
individual Hub validators carry their own licences, so any Hub validator must be
licence-checked before it ships.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agentfox.detection.base import BaseDetector, Detection, DetectionContext


def _type_ok(value: Any, expected: str) -> bool:
    return {
        "string": lambda v: isinstance(v, str),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
        "null": lambda v: v is None,
    }.get(expected, lambda _v: True)(value)


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Return a list of human-readable violations. Empty means valid."""
    errors: list[str] = []
    if not schema:
        return errors

    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, t) for t in types):
            errors.append(f"{path}: expected {'/'.join(types)}, got {type(value).__name__}")
            return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")

    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern {schema['pattern']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than maxItems {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                errors.extend(validate(item, item_schema, f"{path}[{i}]"))

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property '{key}'")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                errors.extend(validate(value[key], sub, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: unexpected property '{key}'")

    return errors


def extract_json(text: str) -> Any | None:
    """Pull JSON out of a model response that may be fenced or prose-wrapped."""
    text = (text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


class JsonSchemaDetector(BaseDetector):
    covers_threats = ("LLM05",)
    key = "schema.json"
    version = "1.0"
    surfaces = ("output", "tool_args")

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        schema = context.schema
        if not schema:
            return []  # no declared contract, nothing to enforce
        parsed = extract_json(content)
        if parsed is None:
            return [
                Detection(
                    entity_type="SCHEMA.UNPARSEABLE",
                    score=1.0,
                    end=len(content),
                    sample="output is not valid JSON",
                    owasp_id="LLM05",
                    detail={"engine": "native"},
                )
            ]
        errors = validate(parsed, schema)
        if not errors:
            return []
        return [
            Detection(
                entity_type="SCHEMA.VIOLATION",
                score=1.0,
                end=len(content),
                sample=f"{len(errors)} violation(s)",
                owasp_id="LLM05",
                detail={"engine": "native", "errors": errors[:20]},
            )
        ]
