"""Pillar 3 — runtime guardrails: detector runs and findings, business rules,
entitlement, sources, escalation, conversation state, feedback, budgets, memory,
inter-agent messages and the judgment posture.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from agentfox.core import ids
from agentfox.core.models.base import Base, TimestampMixin, as_aware, utcnow


class DetectorRun(Base, TimestampMixin):
    """status=timeout|skipped_budget is the latency-budget degradation signal (NOM-RTG-06)."""

    __tablename__ = "detector_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.detector_run_id)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    span_id: Mapped[str | None] = mapped_column(String(40))
    detector_key: Mapped[str] = mapped_column(String(64), index=True)
    detector_version: Mapped[str] = mapped_column(String(32), default="0")
    surface: Mapped[str] = mapped_column(String(24), default="input")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(24), default="ok")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DetectionFinding(Base, TimestampMixin):
    """`sample` is redacted at capture — we never store the raw secret."""

    __tablename__ = "detection_findings"
    __table_args__ = (Index("ix_detfind_entity", "entity_type", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("dfn"))
    detector_run_id: Mapped[str] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    start: Mapped[int] = mapped_column(Integer, default=0)
    end: Mapped[int] = mapped_column(Integer, default=0)
    sample: Mapped[str] = mapped_column(String(200), default="")
    action_taken: Mapped[str] = mapped_column(String(24), default="none")
    owasp_id: Mapped[str | None] = mapped_column(String(24))
    atlas_id: Mapped[str | None] = mapped_column(String(32))


class BusinessRule(Base, TimestampMixin):
    """A stored business guardrail — today a threshold ladder, by kind for what comes next.

    Kept beside policy documents rather than inside them because the two compose by
    different algebras: security rules take the lattice maximum, ladders select exactly
    one band. Flattening them into one list is what makes a refund threshold able to
    silently weaken an injection control.
    """

    __tablename__ = "business_rules"
    __table_args__ = (Index("ix_business_scope", "kind", "tool", "field_path"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("biz"))
    key: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="threshold_ladder")
    #: Who agreed it, so a disagreement has someone to resolve it.
    owner: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    tool: Mapped[str | None] = mapped_column(String(160), index=True)
    field_path: Mapped[str | None] = mapped_column(String(200))
    #: The full authored definition, validated against the kind's schema on write.
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(16), default="observe")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CustomRule(Base, TimestampMixin):
    """A rule a customer writes in their own words: a list of words, patterns or
    topics, or a sequence of tool calls, with an action.

    The definition lives here; enforcement does not. Each row is compiled into a
    rule in the managed `custom` policy pack (`capabilities/detection/custom.py`),
    so it is watched, enforced, simulated, versioned and audited exactly like every
    shipped rule, and the policy engine stays the only place a verdict is decided.
    Content kinds (terms, patterns, topics) are matched by the `custom.lists`
    detector, which is what lets Mask rewrite the matched span; a sequence is a
    registered check, because it is a fact about the run rather than about a string.
    """

    __tablename__ = "custom_rules"
    __table_args__ = (UniqueConstraint("org_id", "key", name="ux_custom_rules_org_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("cus"))
    #: Slug; the policy rule is `custom.<key>` and detections are `CUSTOM.<KEY>`.
    key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    #: terms | patterns | topic | sequence
    kind: Mapped[str] = mapped_column(String(24), default="terms")
    #: For topics: "deny" fires on a match, "allow" fires on content matching none
    #: of the allowed topics (keep the agent on-topic).
    polarity: Mapped[str] = mapped_column(String(8), default="deny")
    entries_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    examples_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    #: Where it applies: surfaces checked, and agents (empty = every agent).
    surfaces_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    agents_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Kind-specific settings, e.g. a sequence's `after` / `then` tool patterns.
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(200), default="")


class DetectorSetting(Base, TimestampMixin):
    """A workspace's choice to switch one detector on or off.

    Overrides `Settings.enabled_detectors` for this tenant only. Absent rows mean
    "as the deployment configured it", so a fresh workspace behaves exactly as
    before and an operator's environment variable still sets the default.
    """

    __tablename__ = "detector_settings"
    __table_args__ = (UniqueConstraint("org_id", "key", name="ux_detector_settings_org_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("dts"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(200), default="")


class CustomModel(Base, TimestampMixin):
    """A classifier the workspace runs itself, called over HTTP as a detector.

    Bring-your-own model: the customer's fine-tuned classifier, an RL-trained
    reward or safety model, anything that answers "which labels, how sure" for a
    piece of text. The `custom.models` detector posts the text to `url` and turns
    labels at or above `threshold` into detections, named so existing rules act on
    them (`INJECTION.*`, `PII.*`) or, under `CUSTOM`, a rule of its own in the
    managed `custom` pack.

    The optional credential is encrypted at rest like every other stored secret
    (`core.crypto`, listed in `platform.keys.rotation.ENCRYPTED_FIELDS`), and is
    never returned by the API.
    """

    __tablename__ = "custom_models"
    __table_args__ = (UniqueConstraint("org_id", "key", name="ux_custom_models_org_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("cmd"))
    key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    surfaces_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: The model's label -> the entity suffix it is reported as ("" ignores the label).
    labels_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    #: CUSTOM | INJECTION | PII | SECRET | SAFETY | ...
    entity_prefix: Mapped[str] = mapped_column(String(32), default="CUSTOM")
    threshold: Mapped[float] = mapped_column(Float, default=0.5)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=800)
    #: open: an unreachable model is recorded and traffic flows. closed: it counts as a hit.
    fail_mode: Mapped[str] = mapped_column(String(8), default="open")
    auth_header: Mapped[str] = mapped_column(String(100), default="")
    auth_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(200), default="")


class EndUserPrincipal(Base, TimestampMixin):
    """The human the agent is acting for.

    Everything else in this pillar depends on this record existing. The Copilot-class
    failure is precisely its absence: the agent runs under its own service identity
    and inherits the union of everything that identity can reach, so every permission
    check passes and the answer still contains what the *requester* was never entitled
    to see.
    """

    __tablename__ = "end_user_principals"
    __table_args__ = (Index("ix_principal_subject", "subject", "agent_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("prn"))
    #: Stable identifier from the caller's IdP — an OIDC `sub`, an employee id.
    subject: Mapped[str] = mapped_column(String(200), index=True)
    display: Mapped[str] = mapped_column(String(200), default="")
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    #: Group and role memberships the entitlement engine resolves against.
    groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: Clearance labels: which restricted classes this person may see at all.
    clearances: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: GDPR Art. 5(1)(b): what this data may be used for.
    purposes: Mapped[list[str]] = mapped_column(JSON, default=list)
    residency: Mapped[str | None] = mapped_column(String(16))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ResourceGrant(Base, TimestampMixin):
    """Who may see which resource, for the native entitlement engine.

    Deliberately a thin ACL rather than a relationship model. Customers who already
    run OpenFGA or Cedar should keep it; this exists so the control is usable by the
    much larger group who have permissions expressed as "this group can read this
    folder" and nothing more formal.
    """

    __tablename__ = "resource_grants"
    __table_args__ = (Index("ix_grant_resource", "resource", "principal_kind", "principal"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("grt"))
    #: Matches the `source` a retriever puts on a chunk, glob allowed.
    resource: Mapped[str] = mapped_column(String(500), index=True)
    principal_kind: Mapped[str] = mapped_column(String(16), default="group")  # group | subject
    principal: Mapped[str] = mapped_column(String(200), index=True)
    #: Restricted classes this resource carries: mnpi, legal_hold, blackout, pii.
    classes: Mapped[list[str]] = mapped_column(JSON, default=list)
    purposes: Mapped[list[str]] = mapped_column(JSON, default=list)
    residency: Mapped[str | None] = mapped_column(String(16))


class DisclosureEvent(Base, TimestampMixin):
    """What was withheld, and why.

    The drop count *is* the oversharing metric. A pre-filter that silently returns
    fewer chunks tells nobody anything; the same filter recording what it removed turns
    "our agent might be oversharing" into a number with examples attached.
    """

    __tablename__ = "disclosure_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("dsc"))
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    principal_subject: Mapped[str | None] = mapped_column(String(200), index=True)
    stage: Mapped[str] = mapped_column(String(16), default="pre")  # pre | post
    candidates: Mapped[int] = mapped_column(Integer, default=0)
    withheld: Mapped[int] = mapped_column(Integer, default=0)
    reasons_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: The agent could reach more than the principal. The diagnostic that
    #: motivates the whole exercise, and valuable before any model exists.
    over_permission: Mapped[float] = mapped_column(Float, default=0.0)


class SourceRecord(Base, TimestampMixin):
    """What a retrieved chunk came from, and whether that source may be trusted.

    Our groundedness scorer checks the answer against the retrieved context and never
    asks whether that context was authoritative. An agent that faithfully grounds an
    answer in a deprecated 2019 wiki page still scores 1.0; this record closes that gap.
    """

    __tablename__ = "source_records"
    __table_args__ = (
        Index("ix_sources_tier", "tier", "domain"),
        UniqueConstraint("org_id", "key", name="ux_source_records_org_key"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("src"))
    #: Stable identifier the retriever emits — URI, doc id, table name.
    key: Mapped[str] = mapped_column(String(500), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    # system_of_record | approved | unverified | external
    tier: Mapped[str] = mapped_column(String(24), default="unverified")
    owner: Mapped[str | None] = mapped_column(String(200))
    #: The corpus this belongs to, so a support agent answering from the finance
    #: corpus is detectable rather than merely unlikely.
    domain: Mapped[str | None] = mapped_column(String(120), index=True)
    updated_at_source: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    freshness_sla_hours: Mapped[int | None] = mapped_column(Integer)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Tiering a source is a claim that it's authoritative — these two fields are the
    #: difference between that claim and a checked fact. A tier says a human decided
    #: this source should be trusted; these say we actually went and looked at what's
    #: there. Only ever set for a `key` that resolves to a fetchable URL — a doc id or
    #: table name has nothing to fetch, and last_validated_at stays null for those,
    #: honestly, rather than faking a check that never happened.
    content_hash: Mapped[str | None] = mapped_column(String(64))
    last_validated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_validation_status: Mapped[str | None] = mapped_column(String(24))
    #: Set only by `agentfox admin seed` — see Agent.is_seed for why this exists.
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)


class SourceConnection(Base, TimestampMixin):
    """How to actually reach a source, for sources that are more than a
    fetchable URL: an enterprise knowledge base or a customer's own database.

    A registry key alone is a claim; this is what turns "validate" from a plain
    HTTP GET into a real connector. `kind` picks which one:

    * ``database`` — dialect/host/port/database/username in `config_json`, the
      password held only as `credential_encrypted`. Validated by connecting and
      introspecting schema, not by fetching arbitrary bytes.
    * ``api`` — `base_url` and an `auth_header` name in `config_json`, the
      bearer token or key held only as `credential_encrypted`. This is the one
      connector that covers Confluence, SharePoint, Notion, Jira and similar —
      they are all an authenticated REST endpoint under the hood, and that is
      the primitive this wraps rather than a vendor-specific SDK per source.
    """

    __tablename__ = "source_connections"
    __table_args__ = (
        UniqueConstraint("org_id", "source_key", name="ux_source_connections_org_key"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("con"))
    #: Matches SourceRecord.key — one connection per registered source.
    source_key: Mapped[str] = mapped_column(String(500), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # database | api
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Never the raw password/token — see crypto.py. Nullable only because a
    #: connection can in principle be unauthenticated (an internal API with no
    #: auth), not because we ever store a secret in the clear.
    credential_encrypted: Mapped[str | None] = mapped_column(Text)


class KnowledgeBoundary(Base, TimestampMixin):
    """What this agent can actually answer from.

    Declared, not inferred. The fact that decides answerability — what the index behind
    the agent contains — is invisible to the model and cannot be derived from the corpus
    without the operator saying so.
    """

    __tablename__ = "knowledge_boundaries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("kbd"))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True, unique=True)
    systems_of_record: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: Rolling window in months, or an absolute start date. Absolute wins.
    coverage_months: Mapped[int | None] = mapped_column(Integer)
    coverage_start: Mapped[dt.date | None] = mapped_column(Date)
    entity_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: fact | aggregate | prediction | opinion | procedure
    answerable_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    out_of_scope_topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    freshness_hours: Mapped[int | None] = mapped_column(Integer)
    #: observe-first, deliberately: an over-refusing agent is uninstalled faster than a
    #: hallucinating one, so enforcement is something an operator turns on knowingly.
    mode: Mapped[str] = mapped_column(String(16), default="observe")


class EscalationPolicy(Base, TimestampMixin):
    """The conditions under which this agent *must* hand off to a human.

    Declared per agent, and deliberately separate from the guardrail policy: a
    guardrail decides whether an action may proceed, an escalation policy decides
    whether a human must be involved. Conflating them means an agent that is behaving
    within policy and still failing the user has nothing that notices.
    """

    __tablename__ = "escalation_policies"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("esc"))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)  # None = default
    #: Condition thresholds. Absent keys are not evaluated.
    conditions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    owner_role: Mapped[str] = mapped_column(String(64), default="support")
    #: An escalation nobody owns within an SLA is a dropped escalation.
    sla_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[str] = mapped_column(String(16), default="observe")  # observe | enforce


class Handoff(Base, TimestampMixin):
    """One hand-off to a human, with its context package and its clock.

    Distinct from `ApprovalRequest`, which asks a human to authorise an *action*. A
    hand-off transfers the *conversation*, and the failure modes are different: an
    approval that expires denies safely, whereas a hand-off that expires leaves a real
    person waiting.
    """

    __tablename__ = "handoffs"
    __table_args__ = (Index("ix_handoffs_status_due", "status", "due_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("hnd"))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    session_id: Mapped[str | None] = mapped_column(String(120), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    #: Which declared conditions triggered it — the audit answer to "why a human?".
    triggers_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: The context the human receives. A hand-off without it is a failure even
    #: though the hand-off itself happened.
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completeness: Mapped[float] = mapped_column(Float, default=0.0)
    owner_role: Mapped[str] = mapped_column(String(64), default="support")
    owner_user_id: Mapped[str | None] = mapped_column(String(40))
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # pending | acknowledged | resolved | breached
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    #: Set when the hand-off was created retroactively by missed-escalation detection
    #: rather than at the time it should have happened.
    detected_retroactively: Mapped[bool] = mapped_column(Boolean, default=False)


class ConversationTurn(Base, TimestampMixin):
    """The per-turn record missed-escalation detection reads back.

    Traces record what the *agent* did. This records what the *conversation* looked
    like, which is what the escalation conditions are written against.
    """

    __tablename__ = "conversation_turns"
    __table_args__ = (Index("ix_turns_session_index", "session_id", "turn_index"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("trn"))
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    turn_index: Mapped[int] = mapped_column(Integer, default=0)
    user_text: Mapped[str] = mapped_column(Text, default="")
    agent_text: Mapped[str] = mapped_column(Text, default="")
    #: Signals extracted at capture time — sentiment, abstention, repetition, topic.
    signals_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)


class GuardrailFeedback(Base, TimestampMixin):
    """A human's verdict on our verdict.

    The measured complaint is that guardrails cannot be tuned: a team gets false
    positives, has nowhere to put that fact, and turns the detector off. This row is
    the place to put it, and the input to both precision reporting and threshold
    recommendation.
    """

    __tablename__ = "guardrail_feedback"
    # One label per decision per person is enforced in application code rather than as
    # a unique constraint, because a deployed table may already hold duplicates and a
    # constraint would make the migration fail on exactly the data it exists to clean.
    __table_args__ = (
        Index("ix_feedback_detector", "detector_key", "label"),
        Index("ix_feedback_decision_actor", "decision_id", "actor"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("gfb"))
    decision_id: Mapped[str | None] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    detector_key: Mapped[str | None] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    # false_positive | true_positive | false_negative
    label: Mapped[str] = mapped_column(String(24), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), default="open")  # open | applied | rejected


class Suppression(Base, TimestampMixin):
    """A scoped, expiring exception to a detector.

    Expiry is not a nicety. A permanent silent exception is indistinguishable from a
    detector that stopped working, and that is exactly how guardrail programmes decay.
    Every suppression carries an owner, a reason and an end date, and every hit is
    counted so an unused one is visible.
    """

    __tablename__ = "suppressions"
    __table_args__ = (Index("ix_suppressions_scope", "agent_id", "detector_key", "entity_type"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("sup"))
    feedback_id: Mapped[str | None] = mapped_column(String(40))
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)  # None = all agents
    detector_key: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    # When set, only this exact matched text is suppressed rather than the whole class.
    sample_hash: Mapped[str | None] = mapped_column(String(64))
    surface: Mapped[str | None] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.UTC)
        return expires > dt.datetime.now(dt.UTC)


class TaintTag(Base, TimestampMixin):
    """The substrate for intent-based containment."""

    __tablename__ = "taint_tags"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("tnt"))
    trace_id: Mapped[str] = mapped_column(String(40), index=True)
    path: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(32))
    trust: Mapped[str] = mapped_column(String(16), default="untrusted")
    propagated_from: Mapped[str | None] = mapped_column(String(300))


class Budget(Base, TimestampMixin):
    """Consumption bounds and loop containment."""

    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("bdg"))
    scope_type: Mapped[str] = mapped_column(String(24), default="agent")
    scope_id: Mapped[str] = mapped_column(String(120), index=True)
    window: Mapped[str] = mapped_column(String(24), default="hour")
    window_started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    max_calls: Mapped[int | None] = mapped_column(Integer)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    max_cost_usd: Mapped[float | None] = mapped_column(Float)
    max_depth: Mapped[int | None] = mapped_column(Integer)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class MemoryEntry(Base, TimestampMixin):
    """NOM-RTG-13 — closes OWASP ASI06 (Memory & Context Poisoning).

    A write into whatever an agent uses as long-term memory (vector store, `mem0`
    -style store, a LangGraph checkpointer) governed the same way a tool call is:
    the detector pipeline runs on the way *in*, not only on the way back out at
    retrieval time, and the entry carries the taint of whatever produced it so a
    later retrieval can weight or refuse it the way source provenance already weights a
    source tier. ``verified_by`` is None until a human or a trusted process confirms the
    entry — until then :attr:`active` defaults closed rather than open, unlike
    :class:`Suppression`: an unconfirmed memory is not entitled to persist
    indefinitely just because nobody has gotten around to revoking it.
    """

    __tablename__ = "memory_entries"
    __table_args__ = (Index("ix_memory_entries_scope", "agent_id", "subject"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.memory_entry_id)
    agent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    subject: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    taint_source: Mapped[str] = mapped_column(String(32), default="user")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decision_id: Mapped[str | None] = mapped_column(String(40))
    verified_by: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.verified_by is not None:
            return True
        if self.expires_at is None:
            return False
        expires = as_aware(self.expires_at)
        return expires > dt.datetime.now(dt.UTC)


class AgentSigningKey(Base, TimestampMixin):
    """NOM-IAM-08 — closes OWASP ASI07 (agent-to-agent message integrity).

    One HMAC secret per agent, encrypted at rest with the same primitive
    :mod:`crypto` already uses for a connected GitHub token or a source
    connection's credential. Signs and verifies A2A traffic where AgentFox is
    the transport (``agentfox.auto()``-wrapped multi-agent calls); traffic on an
    external A2A/MCP bus is reported ``unsigned`` rather than silently trusted.
    """

    __tablename__ = "agent_signing_keys"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.agent_signing_key_id)
    agent_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    key_encrypted: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(200))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AgentMessageLog(Base, TimestampMixin):
    """NOM-IAM-08 — one row per inter-agent message evaluated on the
    ``agent_message`` surface. The ``(org_id, sender_slug, nonce)`` uniqueness is
    the anti-replay mechanism itself, not just an audit convenience: a repeated
    ``(sender, nonce)`` pair fails to insert, and the caller maps that straight
    to a ``replay`` verdict rather than re-deriving replay detection elsewhere.
    """

    __tablename__ = "agent_message_log"
    __table_args__ = (
        UniqueConstraint("org_id", "sender_slug", "nonce", name="ux_agent_message_sender_nonce"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=ids.agent_message_id)
    sender_slug: Mapped[str] = mapped_column(String(120), index=True)
    recipient_slug: Mapped[str | None] = mapped_column(String(120))
    nonce: Mapped[str] = mapped_column(String(64))
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    signature_valid: Mapped[bool | None] = mapped_column(Boolean)
    agent_card_match: Mapped[bool] = mapped_column(Boolean, default=True)
    decision_id: Mapped[str | None] = mapped_column(String(40))
    trace_id: Mapped[str | None] = mapped_column(String(40), index=True)


class JudgmentPosture(Base, TimestampMixin):
    """Which judgment tiers this tenant has turned on, and what may leave the process.

    Separate from :class:`~agentfox.core.config.Settings` on purpose, and the separation is
    the point rather than an accident of storage. Settings are what the *operator of
    the process* chose: environment variables and a config file, read once, unreachable
    from any HTTP request. This row is what an *admin inside the product* chose. The
    two are not interchangeable, because the question "may this deployment talk to a
    third party at all" and the question "do we want it to today" have different
    people answering them and different blast radii when answered wrong.

    So the relationship is one-directional and enforced in
    :mod:`agentfox.capabilities.judgment.posture`: a row here may only ever *narrow* what the
    deployment permits. Enabling a remote tier on a deployment whose ``allow_egress``
    is off is refused rather than stored-and-ignored, because a posture page that
    shows JEV as on while nothing is being sent to JEV is worse than one that will not
    let you turn it on — it answers the compliance question wrongly in writing.

    One row per tenant. ``version`` is bumped on every write for the same reason the
    policy and business-rule tables carry one: an auditor asking what left the building
    in March needs the posture that was in force in March, and the audit chain's
    before/after pair is what reconstructs it.
    """

    __tablename__ = "judgment_posture"
    __table_args__ = (UniqueConstraint("org_id", name="uq_judgment_posture_org"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: ids.new_id("jpo"))
    #: Tier names from :class:`agentfox.capabilities.judgment.Tier`. ``deterministic`` is implicit
    #: and always on — it needs no key, no weights and no network, and a kind with no
    #: permitted decider at all is not a posture anyone meant to choose.
    tiers: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: ``block`` | ``redact`` | ``allow`` — see :class:`agentfox.capabilities.judgment.PiiEgress`.
    pii_egress: Mapped[str] = mapped_column(String(16), default="redact")
    #: Whether a remote tier's outage denies the request or is treated as no-signal.
    fail_closed: Mapped[bool] = mapped_column(Boolean, default=True)
    #: ``local`` | ``remote`` | ``auto``.
    backend: Mapped[str] = mapped_column(String(16), default="local")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(200))
