"""Validate a document against the policy-manifest JSON Schemas in `schema/`.

`jsonschema` is not a dependency, and adding one for three files would be the wrong
trade, so this implements the part of JSON Schema draft 2020-12 those files use:
``type``, ``enum``, ``const``, ``required``, ``properties``,
``additionalProperties``, ``propertyNames``, ``items``, ``minLength``,
``minItems``, ``minProperties``, ``minimum``, ``pattern``, ``uniqueItems``,
``allOf`` / ``anyOf`` / ``oneOf`` / ``not``, ``if`` / ``then`` / ``else`` and
``$ref`` (local ``#/$defs/...`` and a sibling file). A keyword it does not know is
reported, never skipped: a validator that silently ignores part of a schema
reports a document as valid when nobody checked it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).with_name("schema")

#: Keywords that carry no constraint.
_ANNOTATIONS = {"$id", "$schema", "title", "description", "default", "$comment", "examples"}
_HANDLED = {
    "type",
    "enum",
    "const",
    "required",
    "properties",
    "additionalProperties",
    "propertyNames",
    "items",
    "minLength",
    "minItems",
    "minProperties",
    "minimum",
    "pattern",
    "uniqueItems",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "$ref",
    "$defs",
}


@dataclass(frozen=True)
class SchemaError:
    #: Location in the document, e.g. ``/intervention_points/input``.
    path: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {"path": self.path or "/", "message": self.message}


@cache
def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text())


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    return False


def _describe(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, int | float):
        return "number"
    return "string"


class _Validator:
    def __init__(self, root: dict[str, Any]) -> None:
        self.root = root

    def _resolve(self, ref: str) -> tuple[Any, _Validator]:
        target, _, pointer = ref.partition("#")
        validator = self if not target else _Validator(load_schema(Path(target).name))
        node: Any = validator.root
        for part in [p for p in pointer.split("/") if p]:
            node = node[part]
        return node, validator

    def errors(self, schema: Any, value: Any, path: str) -> list[SchemaError]:
        if schema is True:
            return []
        if schema is False:
            return [SchemaError(path, "no value is allowed here")]
        out: list[SchemaError] = []
        for keyword in sorted(set(schema) - _HANDLED - _ANNOTATIONS):
            out.append(SchemaError(path, f"schema keyword '{keyword}' is not checked"))

        if "$ref" in schema:
            node, validator = self._resolve(schema["$ref"])
            out += validator.errors(node, value, path)

        kinds = schema.get("type")
        if kinds is not None:
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if not any(_type_ok(value, k) for k in kinds):
                found = _describe(value)
                return out + [SchemaError(path, f"expected {' or '.join(kinds)}, found {found}")]
        if "enum" in schema and value not in schema["enum"]:
            allowed = ", ".join(json.dumps(v) for v in schema["enum"])
            out.append(SchemaError(path, f"{json.dumps(value)} is not one of {allowed}"))
        if "const" in schema and value != schema["const"]:
            out.append(SchemaError(path, f"must be {json.dumps(schema['const'])}"))

        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                out.append(SchemaError(path, "must not be empty"))
            if "pattern" in schema and not re.search(schema["pattern"], value):
                out.append(SchemaError(path, f"does not match {schema['pattern']}"))
        if isinstance(value, int | float) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                out.append(SchemaError(path, f"must be at least {schema['minimum']}"))
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                out.append(SchemaError(path, f"needs at least {schema['minItems']} item(s)"))
            if schema.get("uniqueItems"):
                seen = [json.dumps(v, sort_keys=True) for v in value]
                if len(seen) != len(set(seen)):
                    out.append(SchemaError(path, "items must be unique"))
            if "items" in schema:
                for i, item in enumerate(value):
                    out += self.errors(schema["items"], item, f"{path}/{i}")
        if isinstance(value, dict):
            out += self._object(schema, value, path)

        for sub in schema.get("allOf", []):
            out += self.errors(sub, value, path)
        if "anyOf" in schema:
            branches = [self.errors(sub, value, path) for sub in schema["anyOf"]]
            if all(branches):
                out.append(SchemaError(path, _any_of_message(schema["anyOf"], branches)))
        if "oneOf" in schema:
            branches = [self.errors(sub, value, path) for sub in schema["oneOf"]]
            passing = sum(1 for b in branches if not b)
            if passing == 0:
                out.append(SchemaError(path, _any_of_message(schema["oneOf"], branches)))
            elif passing > 1:
                out.append(SchemaError(path, "matches more than one allowed shape"))
        if "not" in schema and not self.errors(schema["not"], value, path):
            out.append(SchemaError(path, _not_message(schema["not"])))
        if "if" in schema:
            if not self.errors(schema["if"], value, path):
                if "then" in schema:
                    out += self.errors(schema["then"], value, path)
            elif "else" in schema:
                out += self.errors(schema["else"], value, path)
        return out

    def _object(
        self, schema: dict[str, Any], value: dict[str, Any], path: str
    ) -> list[SchemaError]:
        out: list[SchemaError] = []
        for key in schema.get("required", []):
            if key not in value:
                out.append(SchemaError(path, f"'{key}' is required"))
        if len(value) < schema.get("minProperties", 0):
            out.append(SchemaError(path, f"needs at least {schema['minProperties']} entry"))
        properties = schema.get("properties", {})
        for key, item in value.items():
            where = f"{path}/{key}"
            if "propertyNames" in schema:
                for err in self.errors(schema["propertyNames"], key, where):
                    out.append(SchemaError(where, f"name '{key}': {err.message}"))
            if key in properties:
                out += self.errors(properties[key], item, where)
            elif "additionalProperties" in schema:
                extra = schema["additionalProperties"]
                if extra is False:
                    out.append(SchemaError(where, f"'{key}' is not an allowed field"))
                else:
                    out += self.errors(extra, item, where)
        return out


def _any_of_message(options: list[Any], branches: list[list[SchemaError]]) -> str:
    required = [o.get("required") for o in options if isinstance(o, dict) and o.get("required")]
    if len(required) == len(options) and len({tuple(r) for r in required}) == len(required):
        return "needs at least one of: " + ", ".join("/".join(r) for r in required)
    closest = min(branches, key=len)
    return "; ".join(e.message for e in closest[:2]) or "does not match any allowed shape"


def _not_message(schema: Any) -> str:
    if isinstance(schema, dict) and list(schema) == ["required"]:
        return f"may not set {' and '.join(schema['required'])} together"
    if schema == {}:
        return "this field is not supported"
    return "has a shape that is not allowed"


def validate(document: Any, schema_name: str = "manifest.schema.json") -> list[SchemaError]:
    """Every way ``document`` fails the named schema, in document order."""
    schema = load_schema(schema_name)
    return _Validator(schema).errors(schema, document, "")


__all__ = ["SCHEMA_DIR", "SchemaError", "load_schema", "validate"]
