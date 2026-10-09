"""Rules a customer writes in their own words, matched as detections.

Every managed guardrail product offers the same three controls on its first screen:
a list of words or phrases to block, a pattern (an internal ID, an account number),
and a topic described in plain words. AgentFox's detectors are fixed in code, so a
customer could not say "never mention our competitors" without writing one.

This module is the matching half, and it is deliberately pure: a spec is validated
and compiled into an immutable :class:`CompiledRule`, and :class:`CustomListDetector`
matches content against whichever compiled rules the enforcer hands it in
``DetectionContext.extra["custom_rules"]``. It never reads the database — detectors
run in a thread pool where a session is not safe — and it never decides a verdict.

The deciding half is ordinary policy. Each rule becomes ``custom.<key>`` in the
managed ``custom`` pack (``custom_store.py``), acting on ``CUSTOM.<KEY>`` detections,
so a custom rule is watched, enforced, simulated, tuned and audited exactly like a
shipped one, and Mask rewrites the matched span because a detection has a span.

A ``condition`` compares a value rather than matching words: a field of a tool
call's arguments or result, a reply's length, the first number in it
(``custom_conditions.py``). It is matched here too, so it is decided the same way.

Topics are scored by a :class:`TopicScorer`. The default compares words and runs
anywhere; with the local embedding model installed, meaning is compared instead.
Neither sends anything off the machine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    redact_sample,
)
from agentfox.capabilities.detection.custom_conditions import ConditionSpec
from agentfox.capabilities.detection.custom_conditions import evaluate as evaluate_condition
from agentfox.core.text import content_tokens

KINDS = ("terms", "patterns", "topic", "sequence", "condition")
#: Kinds matched against content by the detector; a sequence is a check.
CONTENT_KINDS = ("terms", "patterns", "topic", "condition")
#: Surfaces a content rule checks when its author did not choose.
DEFAULT_SURFACES = ("input", "output")
CONTENT_SURFACES = (
    "input",
    "output",
    "tool_args",
    "tool_result",
    "retrieved",
    "memory_write",
    "agent_message",
)

MAX_ENTRIES = 500
MAX_PATTERN_LENGTH = 300
#: Content shorter than this many meaningful words is not judged off-topic: a
#: greeting or a "thanks" is not a question about anything.
MIN_TOKENS_FOR_ALLOW = 4

_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
#: Nested quantifiers — `(a+)+`, `(\w*)*` — are the shape of catastrophic
#: backtracking. Python's `re` has no timeout, so they are refused at authoring time.
_NESTED_QUANTIFIER = re.compile(r"\([^)]*[+*][^)]*\)\s*[+*{]")


class SequenceSpec(BaseModel):
    """ "After a tool matching `after`, a call to `then` …", optionally "… unless
    argument `path` matches `allow`" (e.g. the recipient is inside the company)."""

    after: str = Field(min_length=1, max_length=160)
    then: str = Field(min_length=1, max_length=160)
    unless_path: str | None = Field(None, max_length=120)
    unless_matches: str | None = Field(None, max_length=MAX_PATTERN_LENGTH)
    within: Literal["trace", "session"] = "session"

    @field_validator("unless_matches")
    @classmethod
    def _safe(cls, v: str | None) -> str | None:
        return validate_pattern(v) if v else v


class CustomRuleSpec(BaseModel):
    """What a customer authors. Validated here so a bad rule never reaches enforcement."""

    key: str
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["terms", "patterns", "topic", "sequence", "condition"] = "terms"
    polarity: Literal["deny", "allow"] = "deny"
    entries: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    description: str = Field("", max_length=2000)
    surfaces: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    case_sensitive: bool = False
    sequence: SequenceSpec | None = None
    condition: ConditionSpec | None = None
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip().lower()
        if not _KEY.match(v):
            raise ValueError("key: 2–63 lowercase letters, digits, '-' or '_'")
        return v

    @field_validator("entries", "examples")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(e.strip() for e in v if e and e.strip()))
        if len(out) > MAX_ENTRIES:
            raise ValueError(f"at most {MAX_ENTRIES} entries")
        return out

    @field_validator("surfaces")
    @classmethod
    def _surfaces(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in CONTENT_SURFACES]
        if bad:
            raise ValueError(f"unknown surface(s): {', '.join(bad)}")
        return v

    @model_validator(mode="after")
    def _shape(self) -> CustomRuleSpec:
        if self.kind == "sequence":
            if self.sequence is None:
                raise ValueError("a sequence rule needs `sequence`")
            return self
        if self.kind != "condition":
            self.condition = None
        if self.kind == "condition":
            if self.condition is None:
                raise ValueError("a condition rule needs `condition`")
            if self.polarity != "deny":
                raise ValueError("a condition fires when it holds; it has no allowed form")
            # Where it checks is part of the condition, so the two never disagree.
            self.surfaces = [self.condition.surface]
            self.case_sensitive = self.condition.case_sensitive
            return self
        if self.kind in ("terms", "patterns") and not self.entries:
            raise ValueError(f"a {self.kind} rule needs at least one entry")
        if self.kind == "patterns":
            for p in self.entries:
                validate_pattern(p)
        if self.kind == "topic" and not (self.description.strip() or self.examples or self.entries):
            raise ValueError("a topic needs a description, keywords or examples")
        if self.polarity == "allow" and self.kind != "topic":
            raise ValueError("only a topic can be an allowed-topics rule")
        return self

    @property
    def entity(self) -> str:
        return entity_for(self.key)


def entity_for(key: str) -> str:
    return f"CUSTOM.{key.upper().replace('-', '_')}"


def rule_id_for(key: str) -> str:
    return f"custom.{key}"


def validate_pattern(pattern: str) -> str:
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"pattern longer than {MAX_PATTERN_LENGTH} characters")
    if _NESTED_QUANTIFIER.search(pattern):
        raise ValueError(
            f"pattern {pattern!r} nests a repeat inside a repeat, which can hang the matcher"
        )
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"pattern {pattern!r} is not a valid regular expression: {exc}") from exc
    return pattern


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopicProfile:
    """What a topic is, in the author's words: a description, keywords, examples."""

    texts: tuple[str, ...]
    tokens: frozenset[str]


def topic_profile(description: str, entries: list[str], examples: list[str]) -> TopicProfile:
    texts = tuple(t for t in (description, *entries, *examples) if t.strip())
    toks: set[str] = set()
    for t in texts:
        toks |= content_tokens(t)
    return TopicProfile(texts=texts, tokens=frozenset(toks))


class TopicScorer(Protocol):
    """How close a piece of text is to a topic, 0–1."""

    name: str
    threshold: float

    def score(self, text: str, topic: TopicProfile) -> float: ...


class LexicalTopicScorer:
    """Share of the text's meaningful words that the topic's own words cover.

    Offline and deterministic; good at "is this about refunds" when the author gave
    the words people use, weak at paraphrase. The embedding scorer replaces it when
    the local model is installed.
    """

    name = "lexical"
    threshold = 0.34

    def score(self, text: str, topic: TopicProfile) -> float:
        words = content_tokens(text)
        if not words or not topic.tokens:
            return 0.0
        hit = sum(
            1
            for w in words
            if w in topic.tokens or any(w[:5] == t[:5] for t in topic.tokens if len(t) > 5)
        )
        return min(1.0, hit / max(3, min(len(words), 12)))


class EmbeddingTopicScorer:
    """Cosine similarity between the text and the closest of the topic's texts."""

    name = "embedding"
    threshold = 0.55

    def __init__(self, embedder: Any) -> None:
        self._embedder = embedder

    def score(self, text: str, topic: TopicProfile) -> float:  # pragma: no cover - optional model
        if not topic.texts:
            return 0.0
        vectors = self._embedder.embed([text, *topic.texts])
        sims = vectors[1:] @ vectors[0]
        return float(max(0.0, sims.max().item()))


# ---------------------------------------------------------------------------
# Compiled rules and the detector
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledRule:
    key: str
    entity: str
    kind: str
    polarity: str
    surfaces: tuple[str, ...]
    agents: tuple[str, ...]
    regex: re.Pattern[str] | None = None
    topic: TopicProfile | None = None
    condition: ConditionSpec | None = None

    def applies(self, surface: str, agent_slug: str | None) -> bool:
        if surface not in self.surfaces:
            return False
        return not self.agents or (agent_slug is not None and agent_slug in self.agents)


def compile_rule(spec: CustomRuleSpec) -> CompiledRule | None:
    """A matcher for a content rule; None for a sequence (matched by a check)."""
    if spec.kind not in CONTENT_KINDS:
        return None
    flags = 0 if spec.case_sensitive else re.IGNORECASE
    regex = None
    if spec.kind == "terms":
        # Word boundaries where the term starts or ends with a word character, so
        # "Acme" matches "Acme's" but not "Acmeville", and "C++" still matches.
        parts = []
        for term in sorted(spec.entries, key=len, reverse=True):
            esc = re.escape(term)
            left = r"\b" if term[0].isalnum() else ""
            right = r"\b" if term[-1].isalnum() else ""
            parts.append(f"{left}{esc}{right}")
        regex = re.compile("|".join(parts), flags)
    elif spec.kind == "patterns":
        regex = re.compile("|".join(f"(?:{p})" for p in spec.entries), flags)
    topic = (
        topic_profile(spec.description, spec.entries, spec.examples)
        if spec.kind == "topic"
        else None
    )
    return CompiledRule(
        key=spec.key,
        entity=spec.entity,
        kind=spec.kind,
        polarity=spec.polarity,
        surfaces=tuple(spec.surfaces or DEFAULT_SURFACES),
        agents=tuple(spec.agents),
        regex=regex,
        topic=topic,
        condition=spec.condition if spec.kind == "condition" else None,
    )


def _semantic_topics_on(context: DetectionContext) -> bool:
    """Whether `custom.topics` will score topics on this request instead."""
    if not context.enabled_detectors or "custom.topics" not in context.enabled_detectors:
        return False
    from agentfox.capabilities.detection.adapters.embeddings import local_embedder

    return local_embedder().available()


def _calibrated(similarity: float, threshold: float) -> float:
    """A topic match on the scale every other detection uses: 0.5 at the scorer's own
    threshold, 1.0 at a perfect match.

    Scorers differ (lexical overlap matches at 0.34, embeddings at 0.55), and a policy
    rule reads one ``min_score``. Reported raw, a lexical match between 0.34 and the
    rule's default 0.5 was detected and then ignored — the topic matched and nothing
    fired. Calibrated, 0.5 means "matched", and the Low/Medium/High sensitivity levels
    (0.9/0.7/0.5) mean the same thing for topics as for everything else.
    """
    if threshold >= 1.0:
        return 1.0
    return round(min(1.0, 0.5 + 0.5 * (similarity - threshold) / (1.0 - threshold)), 3)


def _topic_detections(
    content: str, rules: list[CompiledRule], context: DetectionContext, scorer: TopicScorer
) -> list[Detection]:
    """Denied topics that match, and allowed topics that all miss."""
    out: list[Detection] = []
    topics = [
        r
        for r in rules
        if r.kind == "topic"
        and r.topic is not None
        and r.applies(context.surface, context.agent_slug)
    ]
    for rule in (r for r in topics if r.polarity == "deny"):
        score = scorer.score(content, rule.topic)  # type: ignore[arg-type]
        if score >= scorer.threshold:
            out.append(
                Detection(
                    entity_type=rule.entity,
                    score=_calibrated(score, scorer.threshold),
                    start=0,
                    end=len(content),
                    sample=redact_sample(content[:80]),
                    detail={
                        "custom_rule": rule.key,
                        "kind": "topic",
                        "scorer": scorer.name,
                        "similarity": round(score, 3),
                    },
                )
            )
    # Allowed topics are judged together: content is off-topic only when it is close
    # to none of them. Each allow-rule reports the miss under its own entity, so each
    # carries its own action and message.
    allowed = [r for r in topics if r.polarity == "allow"]
    if allowed and len(content_tokens(content)) >= MIN_TOKENS_FOR_ALLOW:
        best = max(scorer.score(content, r.topic) for r in allowed)  # type: ignore[arg-type]
        if best < scorer.threshold:
            for rule in allowed:
                out.append(
                    Detection(
                        entity_type=rule.entity,
                        # How far from the nearest allowed topic, calibrated: 0.5 is just
                        # outside it, 1.0 is nowhere near.
                        score=round(
                            min(1.0, 0.5 + 0.5 * (scorer.threshold - best) / scorer.threshold), 3
                        ),
                        start=0,
                        end=len(content),
                        sample=redact_sample(content[:80]),
                        detail={
                            "custom_rule": rule.key,
                            "kind": "off_topic",
                            "scorer": scorer.name,
                        },
                    )
                )
    return out


class CustomListDetector(BaseDetector):
    """The workspace's words, patterns and topics, matched offline.

    Always enabled and free when there are no rules: it reads them from the
    detection context, and an empty list is an immediate return. Topics are scored
    by shared words here; a workspace that turns on `custom.topics` (and has the
    embedding model installed) has them scored by meaning there instead.
    """

    key = "custom.lists"
    version = "1.0"
    surfaces = CONTENT_SURFACES
    #: Custom rules match what was written. Re-scanning decoded variants would
    #: score every topic twice for an evasion customers' own word lists are not
    #: the defence against — the shipped injection and secret detectors are.
    handles_views = True

    def __init__(self, scorer: TopicScorer | None = None) -> None:
        self.scorer = scorer or LexicalTopicScorer()

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        rules: list[CompiledRule] = (context.extra or {}).get("custom_rules") or []
        if not rules or not content:
            return []
        out: list[Detection] = []
        for rule in rules:
            if rule.regex is None or not rule.applies(context.surface, context.agent_slug):
                continue
            for m in rule.regex.finditer(content):
                out.append(
                    Detection(
                        entity_type=rule.entity,
                        score=1.0,
                        start=m.start(),
                        end=m.end(),
                        sample=redact_sample(m.group(0)),
                        detail={"custom_rule": rule.key, "kind": rule.kind},
                    )
                )
        for rule in rules:
            if rule.condition is not None and rule.applies(context.surface, context.agent_slug):
                out.extend(_condition_detections(content, rule, context))
        if any(r.kind == "topic" for r in rules) and not _semantic_topics_on(context):
            out.extend(_topic_detections(content, rules, context, self.scorer))
        return out


def _condition_detections(
    content: str, rule: CompiledRule, context: DetectionContext
) -> list[Detection]:
    """One detection for a condition that holds, at the first value that satisfied it."""
    cond = rule.condition
    tool = context.tool_key or (context.extra or {}).get("tool")
    hits = evaluate_condition(cond, content, tool)  # type: ignore[arg-type]
    if not hits:
        return []
    hit = hits[0]
    start, end = (hit.start, hit.end) if hit.end > hit.start else (0, len(content))
    return [
        Detection(
            entity_type=rule.entity,
            score=1.0,
            start=start,
            end=end,
            sample=redact_sample(content[start:end]),
            detail={
                "custom_rule": rule.key,
                "kind": "condition",
                "field": cond.field,  # type: ignore[union-attr]
                "operator": cond.operator,  # type: ignore[union-attr]
                "matches": len(hits),
            },
        )
    ]


class CustomTopicDetector(BaseDetector):
    """The workspace's topics, scored by meaning with the local embedding model.

    Opt-in (Policies → Library → Detectors): a real forward pass per request with a
    topic rule, so it declares its own allowance and warms the model at startup.
    Nothing leaves the machine.
    """

    key = "custom.topics"
    version = "1.0"
    surfaces = CONTENT_SURFACES
    timeout_ms = 150
    handles_views = True

    def available(self) -> bool:
        from agentfox.capabilities.detection.adapters.embeddings import local_embedder

        return local_embedder().available()

    def _weights_present(self) -> bool:  # pragma: no cover - requires optional dep
        return self.available()

    def warm(self) -> None:  # pragma: no cover - requires optional dependency
        if self.available():
            self._scorer().score("warm", topic_profile("warm", [], []))

    def _scorer(self) -> TopicScorer:  # pragma: no cover - requires optional dependency
        from agentfox.capabilities.detection.adapters.embeddings import local_embedder

        return EmbeddingTopicScorer(local_embedder())

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        rules: list[CompiledRule] = (context.extra or {}).get("custom_rules") or []
        if not content or not any(r.kind == "topic" for r in rules):
            return []
        return _topic_detections(content, rules, context, self._scorer())
