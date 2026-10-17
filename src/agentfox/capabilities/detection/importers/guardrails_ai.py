"""Import a Guardrails AI guard.

Reads the three forms a Guardrails AI guard is written in, without running any of
them:

* **Python** — ``Guard().use(CompetitorCheck(["Globex"], on_fail="exception"))``,
  ``.use(ToxicLanguage, threshold=0.5, on="messages")`` and ``.use_many(...)``. Parsed
  with ``ast``; arguments are read only when they are literals.
* **RAIL** — ``validators="competitor-check: ['Globex']"`` / ``format=`` attributes
  with ``on-fail-<name>`` beside them. Read with a pattern, not an XML parser, so an
  entity-expansion payload in a pasted file is just text.
* **JSON** — ``guard.to_dict()``: ``{"validators": [{"id", "on", "onFail", "kwargs"}]}``.

Each validator maps to what does the same job here (see `MAPPING`): word lists and
topics become custom rules; detection validators switch on our detector and install
the pack whose rules act on it; format validators (length, JSON shape, casing) are
skipped, because AgentFox governs what an agent says and does, not how its output is
formatted. Anything else is skipped with its name, never guessed at.

``on_fail`` carries over: ``exception``/``refrain``/``filter`` block, ``reask``
re-asks, ``fix`` masks where masking is possible, ``noop`` only records.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agentfox.capabilities.detection.custom import CustomRuleSpec
from agentfox.capabilities.detection.importers import ImportPlan, PlanItem

TOOL = "guardrails-ai"
MAX_SOURCE_CHARS = 200_000
INPUT_TARGETS = frozenset({"messages", "prompt", "msg_history", "instructions", "input"})


@dataclass
class Validator:
    """One validator as written, before mapping."""

    name: str
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    on_fail: str = "noop"
    surface: str = "output"
    line: int | None = None

    @property
    def slug(self) -> str:
        return slug_of(self.name)

    def arg(self, name: str, position: int = 0, default: Any = None) -> Any:
        if name in self.kwargs:
            return self.kwargs[name]
        return self.args[position] if len(self.args) > position else default


def slug_of(name: str) -> str:
    """CompetitorCheck, competitor-check, hub://guardrails/competitor_check → competitor_check."""
    tail = re.split(r"[/:]", name.strip())[-1]
    tail = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", tail)
    return re.sub(r"[^a-z0-9]+", "_", tail.lower()).strip("_")


# --- Reading ---------------------------------------------------------------------


def parse(source: str) -> tuple[list[Validator], list[str]]:
    """The validators in a guard, in whichever form it is written."""
    source = source[:MAX_SOURCE_CHARS]
    text = source.strip()
    if not text:
        return [], ["nothing to import"]
    if text.startswith("{") or text.startswith("["):
        return _from_json(text)
    if text.startswith("<"):
        return _from_rail(text)
    return _from_python(source)


def _from_json(text: str) -> tuple[list[Validator], list[str]]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        return [], [f"not valid JSON: {exc.msg}"]
    guards = data if isinstance(data, list) else [data]
    out: list[Validator] = []
    for guard in guards:
        for v in (guard or {}).get("validators") or []:
            if not isinstance(v, dict) or not (v.get("id") or v.get("name")):
                continue
            target = str(v.get("on") or "$")
            out.append(
                Validator(
                    name=str(v.get("id") or v.get("name")),
                    kwargs=dict(v.get("kwargs") or {}),
                    on_fail=_on_fail(v.get("onFail") or v.get("on_fail")),
                    surface="input" if target in INPUT_TARGETS else "output",
                )
            )
    return out, []


_RAIL_ATTR = re.compile(r'\b(validators|format)\s*=\s*"([^"]*)"')
_RAIL_ON_FAIL = re.compile(r'\bon-fail-([\w-]+)\s*=\s*"([^"]*)"')


def _from_rail(text: str) -> tuple[list[Validator], list[str]]:
    on_fail = {slug_of(k): v for k, v in _RAIL_ON_FAIL.findall(text)}
    out: list[Validator] = []
    for m in _RAIL_ATTR.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        section = text[: m.start()]
        surface = (
            "input"
            if section.rfind("<prompt") > section.rfind("</prompt")
            or section.rfind("<messages") > section.rfind("</messages")
            else "output"
        )
        for part in m.group(2).split(";"):
            name, _, arg = part.strip().partition(":")
            if not name.strip():
                continue
            args = [_literal_text(a) for a in _split_args(arg.strip())] if arg.strip() else []
            out.append(
                Validator(
                    name=name.strip(),
                    args=args,
                    on_fail=_on_fail(on_fail.get(slug_of(name))),
                    surface=surface,
                    line=line,
                )
            )
    return out, []


def _split_args(text: str) -> list[str]:
    """RAIL separates arguments with spaces, except inside brackets or quotes."""
    parts, depth, quote, buf = [], 0, "", ""
    for ch in text:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        elif ch == " " and depth == 0:
            if buf:
                parts.append(buf)
            buf = ""
            continue
        buf += ch
    return parts + ([buf] if buf else [])


def _literal_text(text: str) -> Any:
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def _from_python(source: str) -> tuple[list[Validator], list[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [], [f"could not read the Python (line {exc.lineno}): {exc.msg}"]
    out: list[Validator] = []
    # In the order written: `ast.walk` visits a chain `.use(a).use(b)` outside-in.
    calls = sorted(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _call_name(n) in ("use", "use_many")
        ),
        key=lambda n: (n.func.end_lineno or 0, n.func.end_col_offset or 0),
    )
    for node in calls:
        target = _literal(_kw(node, "on")) or "output"
        surface = "input" if target in INPUT_TARGETS else "output"
        if _call_name(node) == "use" and node.args and not isinstance(node.args[0], ast.Call):
            # .use(ToxicLanguage, threshold=0.5, on_fail="exception"): the class, then its
            # arguments.
            out.append(
                _validator(
                    _call_name(node.args[0]), node.args[1:], node.keywords, surface, node.lineno
                )
            )
            continue
        for arg in node.args:
            if isinstance(arg, ast.Call):
                out.append(_validator(_call_name(arg), arg.args, arg.keywords, surface, arg.lineno))
    return out, []


def _validator(
    name: str, args: list[ast.expr], keywords: list[ast.keyword], surface: str, line: int
) -> Validator:
    kwargs = {k.arg: _literal(k.value) for k in keywords if k.arg and k.arg != "on"}
    return Validator(
        name=name,
        args=[_literal(a) for a in args],
        kwargs={k: v for k, v in kwargs.items() if k != "on_fail"},
        on_fail=_on_fail(kwargs.get("on_fail")),
        surface=surface,
        line=line,
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _kw(node: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in node.keywords if k.arg == name), None)


def _literal(node: ast.expr | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        # OnFailAction.EXCEPTION and friends: the attribute name is the value.
        return node.attr.lower() if isinstance(node, ast.Attribute) else None


def _on_fail(value: Any) -> str:
    v = str(value or "noop").lower().rsplit(".", 1)[-1]
    return (
        v
        if v in ("exception", "refrain", "filter", "reask", "fix", "fix_reask", "noop", "custom")
        else "noop"
    )


# --- Mapping ---------------------------------------------------------------------


def _action(v: Validator, *, maskable: bool = False) -> tuple[str, str, str]:
    """(effect, on_block, note) for a validator's on_fail."""
    if v.on_fail in ("reask", "fix_reask"):
        return "block", "reask", "Re-asks the model, as in Guardrails"
    if v.on_fail == "fix":
        return (
            ("redact", "refuse", "Masks the match")
            if maskable
            else ("block", "refuse", "No fix here: blocks")
        )
    if v.on_fail == "noop":
        return "allow", "refuse", "Records only, as in Guardrails"
    return "block", "refuse", ""


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, list | tuple):
        return [str(s).strip() for s in value if str(s).strip()]
    return []


class _Keys:
    def __init__(self, taken: set[str]):
        self.taken = set(taken)

    def __call__(self, base: str) -> str:
        key = f"gr-{base}".replace("_", "-")[:60]
        out, n = key, 2
        while out in self.taken:
            out, n = f"{key}-{n}", n + 1
        self.taken.add(out)
        return out


Mapper = Callable[[Validator, _Keys], list[PlanItem]]


def _rule_item(v: Validator, keys: _Keys, base: str, title: str, **spec: Any) -> list[PlanItem]:
    effect, on_block, note = _action(v, maskable=spec.get("kind") in ("terms", "patterns"))
    try:
        rule = CustomRuleSpec(key=keys(base), name=title, surfaces=[v.surface], **spec)
    except ValidationError as exc:
        return [
            PlanItem(
                v.name,
                "skipped",
                note=f"Could not read its arguments: {exc.errors()[0]['msg']}",
                line=v.line,
            )
        ]
    return [PlanItem(v.name, "custom_rule", rule.key, title, note, effect, on_block, rule, v.line)]


def _terms(arg: str, title: str) -> Mapper:
    def build(v: Validator, keys: _Keys) -> list[PlanItem]:
        words = _strings(v.arg(arg))
        if not words:
            return [PlanItem(v.name, "skipped", note="No words given", line=v.line)]
        return _rule_item(v, keys, v.slug, title, kind="terms", entries=words)

    return build


def _topics(v: Validator, keys: _Keys) -> list[PlanItem]:
    items: list[PlanItem] = []
    allowed = _strings(v.arg("valid_topics"))
    denied = _strings(v.arg("invalid_topics", 1))
    if allowed:
        items += _rule_item(
            v,
            keys,
            "allowed-topics",
            "Allowed topics",
            kind="topic",
            polarity="allow",
            description=", ".join(allowed),
        )
    if denied:
        items += _rule_item(
            v,
            keys,
            "denied-topics",
            "Off-limits topics",
            kind="topic",
            description=", ".join(denied),
        )
    return items or [PlanItem(v.name, "skipped", note="No topics given", line=v.line)]


def _denied_topic(arg: str | None, title: str, fallback: str = "") -> Mapper:
    def build(v: Validator, keys: _Keys) -> list[PlanItem]:
        topics = _strings(v.arg(arg)) if arg else []
        description = ", ".join(topics) or fallback
        if not description:
            return [PlanItem(v.name, "skipped", note="No topics given", line=v.line)]
        return _rule_item(v, keys, v.slug, title, kind="topic", description=description)

    return build


def _covered(pack: str, title: str, detector: str = "", detector_title: str = "") -> Mapper:
    """A validator our own detectors already cover: switch the detector on, install the pack.

    The pack's rules keep their own actions; its `on_fail` is not carried over, because
    one pack rule may be serving several validators that disagreed.
    """

    def build(v: Validator, _keys: _Keys) -> list[PlanItem]:
        items = []
        if detector:
            items.append(
                PlanItem(
                    v.name,
                    "detector",
                    detector,
                    detector_title,
                    "Switched on",
                    effect="",
                    line=v.line,
                )
            )
        items.append(
            PlanItem(v.name, "pack", pack, title, "Installed watching", effect="", line=v.line)
        )
        return items

    return build


#: Guardrails names whose native port is called something else.
NATIVE_ALIASES = {
    "lower_case": "lowercase",
    "upper_case": "uppercase",
    "valid_choices": "valid_choice",
    "valid_openapi_spec": "valid_open_api_spec",
    "readability": "reading_level",
    "is_high_quality_translation": "high_quality_translation",
    "high_quality_translation_validator": "high_quality_translation",
    "detect_system_prompt_leakage": "system_prompt_leak",
    "sql_column_presence_validator": "sql_column_presence",
    "valid_python_validator": "valid_python",
    "similar_to_list": "similar_to_previous_values",
    "detect_many_shot_jailbreak": "many_shot_jailbreak",
    "sainatha_prompt_injection_detector": "prompt_injection_llm",
}


#: Ports that report the span they object to, so `on_fail="fix"` can mask it.
MASKABLE = frozenset(
    {"ban_list", "competitor_check", "mentions_drugs", "internal_domains", "quotes_price"}
)


def _native(v: Validator, keys: _Keys) -> list[PlanItem]:
    """The validator's own port (`detection/validators/`), with the same settings.

    Positional arguments are read in the order the port declares its settings, which
    follows upstream's constructor. A port that runs with no settings and is offered
    as a detector is switched on; anything else becomes a validator rule, so its
    settings and its `on_fail` carry over.
    """
    from agentfox.capabilities.detection.validators import get_validator

    name = NATIVE_ALIASES.get(v.slug, v.slug)
    validator = get_validator(name)
    if validator is None:
        return [PlanItem(v.name, "skipped", note="No match in AgentFox yet", line=v.line)]
    fields = list(validator.Params.model_fields)
    raw = {k: a for k, a in zip(fields, v.args, strict=False) if a is not None}
    raw.update({k: a for k, a in v.kwargs.items() if k in validator.Params.model_fields})
    if not raw and validator.detector and validator.standalone():
        return [
            PlanItem(
                v.name,
                "detector",
                f"validator.{name}",
                validator.label or name,
                "Switched on",
                effect="",
                line=v.line,
            )
        ]
    surface = v.surface if v.surface in validator.surfaces else validator.surfaces[0]
    effect, on_block, note = _action(v, maskable=name in MASKABLE)
    try:
        rule = CustomRuleSpec(
            key=keys(v.slug),
            name=validator.label or name,
            kind="validator",
            validator={"name": name, "params": raw},
            surfaces=[surface],
        )
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"].removeprefix("Value error, ")
        return [
            PlanItem(v.name, "skipped", note=f"Could not read its settings: {msg}", line=v.line)
        ]
    if not validator.available():
        note = (
            f"{note + '. ' if note else ''}Not runnable here yet: {validator.unavailable_reason()}"
        )
    return [
        PlanItem(v.name, "custom_rule", rule.key, rule.name, note, effect, on_block, rule, v.line)
    ]


def _skip(reason: str) -> Mapper:
    return lambda v, _keys: [PlanItem(v.name, "skipped", note=reason, line=v.line)]


MAPPING: dict[str, Mapper] = {
    # Word lists and topics → custom rules.
    # Ported natively with the same matching (fuzzy, word-boundary), so they keep
    # their exact behaviour rather than becoming a plain word list.
    "competitor_check": _native,
    "ban_list": _native,
    "restrict_to_topic": _topics,
    "sensitive_topic": _denied_topic("sensitive_topics", "Sensitive topics"),
    "sensitive_topics": _denied_topic("sensitive_topics", "Sensitive topics"),
    "mentions_drugs": _native,
    # Detection our detectors already do → the detector plus the pack that acts on it.
    "detect_pii": _covered("baseline", "Personal data (PII)"),
    "guardrails_pii": _covered("baseline", "Personal data (PII)"),
    "secrets_present": _covered("baseline", "Secrets and keys"),
    "detect_jailbreak": _covered(
        "baseline", "Prompt injection", "injection.classifier", "Injection model"
    ),
    "detect_prompt_injection": _covered(
        "baseline", "Prompt injection", "injection.classifier", "Injection model"
    ),
    "unusual_prompt": _covered("baseline", "Prompt injection"),
    "detect_system_prompt_leakage": _native,
    "toxic_language": _covered("baseline", "Harmful content", "safety.lexicon", "Harmful content"),
    "profanity_free": _covered("baseline", "Harmful content", "safety.lexicon", "Harmful content"),
    "nsfw_text": _covered("baseline", "Harmful content", "safety.lexicon", "Harmful content"),
    "valid_json": _covered("baseline", "Malformed tool arguments", "schema.json", "JSON shape"),
    "provenance_llm": _covered(
        "agent-integrity", "Unsupported answers", "grounding.nli", "Grounding model"
    ),
    "provenance_embeddings": _covered(
        "agent-integrity", "Unsupported answers", "grounding.nli", "Grounding model"
    ),
    "grounded_ai_hallucination": _covered(
        "agent-integrity", "Unsupported answers", "grounding.nli", "Grounding model"
    ),
    "bespoke_minicheck": _covered(
        "agent-integrity", "Unsupported answers", "grounding.nli", "Grounding model"
    ),
    "exclude_sql_predicates": _native,
    # Everything else with a native port (formatting, structure, LLM judges) is read
    # by `_native` in `plan`, so no list here can fall behind the ports.
}


def plan(source: str, *, existing_keys: set[str] | None = None) -> ImportPlan:
    """What importing this guard would do. Writes nothing."""
    validators, errors = parse(source)
    result = ImportPlan(tool=TOOL, errors=errors)
    keys = _Keys(existing_keys or set())
    for v in validators:
        result.items.extend(MAPPING.get(v.slug, _native)(v, keys))
    if not validators and not errors:
        result.errors.append(
            "No validators found. Paste the code that builds your Guard, "
            "a .rail file or guard.to_dict()."
        )
    if any(i.rule and i.rule.kind == "topic" for i in result.items):
        result.items.append(
            PlanItem(
                "topics",
                "detector",
                "custom.topics",
                "Topic model",
                "Switched on for better topic matching",
                effect="",
            )
        )
    _dedupe(result)
    return result


def _dedupe(result: ImportPlan) -> None:
    """One switch per detector and one install per pack, however many validators asked."""
    first: dict[tuple[str, str], PlanItem] = {}
    items = []
    for item in result.items:
        if item.kind in ("detector", "pack"):
            kept = first.get((item.kind, item.target))
            if kept is not None:
                kept.source = ", ".join(dict.fromkeys([*kept.source.split(", "), item.source]))
                kept.title = ", ".join(dict.fromkeys([*kept.title.split(", "), item.title]))
                continue
            first[(item.kind, item.target)] = item
        items.append(item)
    result.items = items
