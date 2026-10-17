"""Bring your own model: a classifier the workspace runs, called over HTTP as a detector.

A customer with their own fine-tuned classifier (or an RL-trained safety or reward
model; to this module it is the same thing: text in, labels and scores out) should
not have to fork a detector to use it. They register an endpoint, say which labels
mean what, and the `custom.models` detector posts each checked text to it and turns
labels at or above the threshold into detections.

What a detection is called decides what acts on it:

* `INJECTION`, `PII`, `SECRET`, `SAFETY` ...: reported as `<PREFIX>.<LABEL>`, so the
  rules that already act on that kind of problem act on this model too.
* `CUSTOM`: reported as `CUSTOM.<KEY>`, with a rule of its own in the managed `custom`
  pack (`custom_store.sync_policy`), watched first and tuned like any other.

**Failing safely.** The endpoint is somebody else's server. A timeout, an error or an
unreadable answer is recorded on the detector run (status `error`, the reason in
`raw`) and never, by itself, blocks traffic: with `fail_mode="open"` (the default)
the request goes on unchecked by this model. `fail_mode="closed"` turns an outage
into a hit on the model's own entity, so whatever rule acts on the model acts on its
absence. That is the operator's explicit choice, per model.

**Egress.** Posting text to a model sends customer content off the process. An
endpoint on a public address is called only when the deployment allows egress
(`allow_egress`); one on this deployment's own network only when it allows private
hosts (`outbound_allow_private_hosts`); link-local (cloud metadata) never. Every call
goes through `core.outbound.guarded_post`, which pins the vetted address and refuses
redirects.

The detector never reads the database (it runs in a thread pool where a session is
not safe): the enforcer compiles the workspace's models, credentials decrypted, into
``DetectionContext.extra["custom_models"]``.
"""

from __future__ import annotations

import ipaddress
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    DetectorResult,
)
from agentfox.capabilities.detection.custom import CONTENT_SURFACES, DEFAULT_SURFACES, entity_for
from agentfox.core import outbound
from agentfox.core.config import get_settings
from agentfox.core.crypto import DecryptionFailed, EncryptionNotConfigured, decrypt_secret
from agentfox.core.models import CustomModel
from agentfox.platform.ledger import operator_log

DETECTOR_KEY = "custom.models"

#: Entity prefixes a model may report under. The shipped policies act on these.
PREFIXES = ("CUSTOM", "INJECTION", "PII", "SECRET", "SAFETY", "TOPIC", "BRAND", "GROUNDING")

#: Labels that mean "nothing found" when the operator gave no label mapping.
NEGATIVE_LABELS = frozenset(
    {"benign", "safe", "none", "negative", "ok", "clean", "normal", "legit", "label_0", "no"}
)

MIN_TIMEOUT_MS = 50
MAX_TIMEOUT_MS = 2000
MAX_RESPONSE_BYTES = 256_000

_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_HEADER = re.compile(r"^[A-Za-z0-9-]{1,100}$")
_SUFFIX = re.compile(r"[^A-Z0-9]+")


class ModelUnavailable(RuntimeError):
    """The model could not answer: refused, unreachable, or answered nonsense."""


# ---------------------------------------------------------------------------
# What an operator registers
# ---------------------------------------------------------------------------


class CustomModelSpec(BaseModel):
    key: str
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8, max_length=1000)
    surfaces: list[str] = Field(default_factory=lambda: list(DEFAULT_SURFACES))
    #: The model's label -> the suffix it is reported as. Empty: every label except
    #: the obviously negative ones, reported under its own name.
    labels: dict[str, str] = Field(default_factory=dict)
    entity_prefix: str = "CUSTOM"
    threshold: float = Field(0.5, ge=0.0, le=1.0)
    timeout_ms: int = Field(800, ge=MIN_TIMEOUT_MS, le=MAX_TIMEOUT_MS)
    fail_mode: Literal["open", "closed"] = "open"
    auth_header: str = ""
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip().lower()
        if not _KEY.match(v):
            raise ValueError("key: 2-63 lowercase letters, digits, '-' or '_'")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        try:
            url = httpx.URL(v)
        except (httpx.InvalidURL, TypeError, ValueError) as exc:
            raise ValueError(f"not a valid URL: {exc}") from exc
        if url.scheme not in ("http", "https") or not url.host:
            raise ValueError("the model URL must be http(s) with a host")
        return v

    @field_validator("surfaces")
    @classmethod
    def _surfaces(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in CONTENT_SURFACES]
        if bad:
            raise ValueError(f"unknown surface(s): {', '.join(bad)}")
        return list(dict.fromkeys(v)) or list(DEFAULT_SURFACES)

    @field_validator("labels")
    @classmethod
    def _labels(cls, v: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for label, suffix in (v or {}).items():
            label = str(label).strip()
            if label:
                out[label] = _suffix(str(suffix or ""))
        if len(out) > 100:
            raise ValueError("at most 100 labels")
        return out

    @field_validator("entity_prefix")
    @classmethod
    def _prefix(cls, v: str) -> str:
        v = (v or "CUSTOM").strip().upper()
        if v not in PREFIXES:
            raise ValueError(f"entity_prefix must be one of {', '.join(PREFIXES)}")
        return v

    @field_validator("auth_header")
    @classmethod
    def _header(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not _HEADER.match(v):
            raise ValueError("auth_header must be a header name, like Authorization or X-Api-Key")
        return v


def _suffix(label: str) -> str:
    return _SUFFIX.sub("_", label.strip().upper()).strip("_")


# ---------------------------------------------------------------------------
# Compiled, ready for the detector
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledModel:
    key: str
    url: str
    surfaces: tuple[str, ...]
    labels: dict[str, str]
    entity_prefix: str
    threshold: float
    timeout_ms: int
    fail_mode: str
    headers: dict[str, str] = field(default_factory=dict)
    #: Set when the model cannot be called at all (its credential will not decrypt).
    error: str | None = None

    def entity(self, label: str) -> str | None:
        """What a label is reported as, or None if this label is not a finding."""
        if self.labels:
            lookup = {k.lower(): v for k, v in self.labels.items()}
            suffix = lookup.get(label.lower())
            if not suffix:
                return None
        else:
            if label.strip().lower() in NEGATIVE_LABELS:
                return None
            suffix = _suffix(label) or "MATCH"
        if self.entity_prefix == "CUSTOM":
            return entity_for(self.key)
        return f"{self.entity_prefix}.{suffix}"

    def unavailable_entity(self) -> str:
        if self.entity_prefix == "CUSTOM":
            return entity_for(self.key)
        return f"{self.entity_prefix}.MODEL_UNAVAILABLE"


def spec_of(row: CustomModel) -> CustomModelSpec:
    return CustomModelSpec(
        key=row.key,
        name=row.name or row.key,
        url=row.url,
        surfaces=list(row.surfaces_json or []),
        labels=dict(row.labels_json or {}),
        entity_prefix=row.entity_prefix or "CUSTOM",
        threshold=row.threshold,
        timeout_ms=row.timeout_ms,
        fail_mode=row.fail_mode if row.fail_mode in ("open", "closed") else "open",
        auth_header=row.auth_header or "",
        enabled=row.enabled,
    )


def compile_model(row: CustomModel) -> CompiledModel:
    spec = spec_of(row)
    headers: dict[str, str] = {}
    error = None
    if spec.auth_header and row.auth_secret_encrypted:
        try:
            headers[spec.auth_header] = decrypt_secret(row.auth_secret_encrypted)
        except (EncryptionNotConfigured, DecryptionFailed):
            error = "its stored credential could not be decrypted on this deployment"
    return CompiledModel(
        key=spec.key,
        url=spec.url,
        surfaces=tuple(spec.surfaces),
        labels=spec.labels,
        entity_prefix=spec.entity_prefix,
        threshold=spec.threshold,
        timeout_ms=spec.timeout_ms,
        fail_mode=spec.fail_mode,
        headers=headers,
        error=error,
    )


def list_models(session: Session) -> list[CustomModel]:
    return list(session.scalars(select(CustomModel).order_by(CustomModel.key)))


def get_model(session: Session, key: str) -> CustomModel | None:
    return session.scalar(select(CustomModel).where(CustomModel.key == key))


def compiled_models(session: Session) -> list[CompiledModel]:
    """The workspace's enabled models, ready for the detector. A row that no longer
    validates is skipped, never fatal."""
    out: list[CompiledModel] = []
    for row in session.scalars(select(CustomModel).where(CustomModel.enabled.is_(True))):
        try:
            out.append(compile_model(row))
        except ValueError:
            continue
    return out


def any_enabled(session: Session) -> bool:
    return (
        session.scalar(select(CustomModel.id).where(CustomModel.enabled.is_(True)).limit(1))
        is not None
    )


# ---------------------------------------------------------------------------
# Calling one
# ---------------------------------------------------------------------------


def egress_refusal(url: str) -> str | None:
    """Why this deployment must not send content to ``url``, or None.

    The address checks are `core.outbound`'s (private hosts, link-local never); on
    top, a publicly routable address is customer content leaving the deployment,
    which only `allow_egress` permits.
    """
    try:
        ip = outbound.vet(httpx.URL(url), "the model endpoint")
    except (outbound.OutboundRefused, httpx.InvalidURL, ValueError) as exc:
        return str(exc)
    if ipaddress.ip_address(ip).is_global and not get_settings().allow_egress:
        return (
            "the endpoint is on the public internet and this deployment has egress "
            "switched off (AGENTFOX_ALLOW_EGRESS). Host the model on this deployment's "
            "own network, or turn egress on where the gateway runs"
        )
    return None


def parse_labels(body: Any) -> list[tuple[str, float]]:
    """(label, score) pairs from the shapes classifier servers answer with.

    Accepted: ``{"labels": [{"label", "score"}]}``, a list of those (Hugging Face
    text-classification, nested one level or not), ``{"label", "score"}``, and
    ``{"scores": {label: score}}`` or a plain ``{label: score}`` map.
    """
    if isinstance(body, dict):
        if "labels" in body and isinstance(body["labels"], list | dict):
            return parse_labels(body["labels"])
        if "scores" in body and isinstance(body["scores"], dict):
            return parse_labels(body["scores"])
        if "label" in body:
            return [(str(body["label"]), _score(body.get("score", 1.0)))]
        if body and all(isinstance(v, int | float) for v in body.values()):
            return [(str(k), _score(v)) for k, v in body.items()]
        raise ModelUnavailable("the model answered JSON without labels")
    if isinstance(body, list):
        out: list[tuple[str, float]] = []
        for item in body:
            if isinstance(item, list):
                out.extend(parse_labels(item))
            elif isinstance(item, dict) and "label" in item:
                out.append((str(item["label"]), _score(item.get("score", 1.0))))
        return out
    raise ModelUnavailable("the model's answer was not JSON labels")


def _score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError) as exc:
        raise ModelUnavailable(f"score {value!r} is not a number") from exc


def call_model(model: CompiledModel, content: str, surface: str) -> list[tuple[str, float]]:
    """Post one text to the model; its labels and scores. Raises `ModelUnavailable`."""
    if model.error:
        raise ModelUnavailable(model.error)
    refused = egress_refusal(model.url)
    if refused:
        raise ModelUnavailable(refused)
    try:
        resp = outbound.guarded_post(
            model.url,
            what=f"the '{model.key}' model",
            # `text` for a purpose-built server; `inputs` is what Hugging Face
            # inference endpoints and text-embeddings-inference expect.
            json_body={"text": content, "inputs": content, "surface": surface},
            max_bytes=MAX_RESPONSE_BYTES,
            timeout=model.timeout_ms / 1000,
            headers=model.headers,
        )
        body = resp.json()
    except outbound.OutboundRefused as exc:
        raise ModelUnavailable(str(exc)) from exc
    except ValueError as exc:
        raise ModelUnavailable("the model did not answer with JSON") from exc
    return parse_labels(body)


def detections_for(
    model: CompiledModel, labels: list[tuple[str, float]], content: str
) -> list[Detection]:
    out: list[Detection] = []
    for label, score in labels:
        if score < model.threshold:
            continue
        entity = model.entity(label)
        if entity is None:
            continue
        out.append(
            Detection(
                entity_type=entity,
                score=score,
                start=0,
                end=len(content),
                detail={"custom_model": model.key, "label": label},
            )
        )
    return out


_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="nom-custom-model")


class CustomModelDetector(BaseDetector):
    """The workspace's own models, called over HTTP. See the module docstring."""

    key = DETECTOR_KEY
    version = "1.0"
    surfaces = CONTENT_SURFACES
    handles_views = True
    #: A network round trip to someone else's server. The heavy pool keeps a slow
    #: model from starving the local detectors, and the pipeline grants the budget
    #: only to a workspace that registered a model (`detector_settings.enabled_for`).
    #: Each model's own `timeout_ms` bounds the actual wait.
    timeout_ms = MAX_TIMEOUT_MS + 200
    requires_budget_ms = MAX_TIMEOUT_MS + 200

    def detect(self, content: str, context: DetectionContext) -> DetectorResult:
        models: list[CompiledModel] = [
            m
            for m in (context.extra or {}).get("custom_models") or []
            if context.surface in m.surfaces
        ]
        result = DetectorResult(detector_key=self.key, version=self.version)
        if not models or not (content or "").strip():
            return result

        def run(model: CompiledModel) -> tuple[CompiledModel, Any]:
            try:
                return model, call_model(model, content, context.surface)
            except ModelUnavailable as exc:
                return model, exc
            except Exception as exc:  # noqa: BLE001 - one model must never fail the rest
                return model, ModelUnavailable(f"{type(exc).__name__}: {exc}")

        answers = [run(models[0])] if len(models) == 1 else list(_POOL.map(run, models))
        degraded: list[dict[str, str]] = []
        for model, answer in answers:
            if isinstance(answer, ModelUnavailable):
                degraded.append({"model": model.key, "error": str(answer)[:300]})
                if model.fail_mode == "closed":
                    result.detections.append(
                        Detection(
                            entity_type=model.unavailable_entity(),
                            score=1.0,
                            start=0,
                            end=len(content),
                            detail={"custom_model": model.key, "unavailable": True},
                        )
                    )
                continue
            result.detections.extend(detections_for(model, answer, content))
        result.score = max((d.score for d in result.detections), default=0.0)
        if degraded:
            # Recorded, not raised: `error` is reported on the run and in the
            # pipeline's `errored`, which never by itself fails a request closed.
            result.status = "error"
            result.raw = {"degraded": degraded}
        return result


# ---------------------------------------------------------------------------
# Writing, audited (`operator_log.PRIVILEGED`)
# ---------------------------------------------------------------------------


def row_json(row: CustomModel) -> dict[str, Any]:
    """The API shape. The credential is never included, only whether there is one."""
    return {
        "key": row.key,
        "name": row.name,
        "url": row.url,
        "surfaces": list(row.surfaces_json or []),
        "labels": dict(row.labels_json or {}),
        "entity_prefix": row.entity_prefix,
        "entity": (
            entity_for(row.key) if row.entity_prefix == "CUSTOM" else f"{row.entity_prefix}.<LABEL>"
        ),
        "rule_id": f"custom.{row.key}" if row.entity_prefix == "CUSTOM" else None,
        "threshold": row.threshold,
        "timeout_ms": row.timeout_ms,
        "fail_mode": row.fail_mode,
        "auth_header": row.auth_header,
        "has_secret": bool(row.auth_secret_encrypted),
        "enabled": row.enabled,
        "version": row.version,
        "created_by": row.created_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _audit_json(row: CustomModel) -> dict[str, Any]:
    out = row_json(row)
    out.pop("updated_at", None)
    return out


def save_model(
    session: Session,
    spec: CustomModelSpec,
    *,
    actor: str,
    secret_ciphertext: str | None = None,
    clear_secret: bool = False,
    effect: str = "block",
    reason: str = "",
) -> CustomModel:
    """Create or update one model. A `CUSTOM` model's rule is (re)generated in the
    managed `custom` pack, starting in the pack's current mode with ``effect``."""
    from agentfox.capabilities.detection.custom_store import sync_policy

    row = get_model(session, spec.key)
    before = _audit_json(row) if row else None
    if row is None:
        row = CustomModel(key=spec.key, created_by=actor)
        session.add(row)
    else:
        row.version = (row.version or 1) + 1
    row.name = spec.name
    row.url = spec.url
    row.surfaces_json = spec.surfaces
    row.labels_json = spec.labels
    row.entity_prefix = spec.entity_prefix
    row.threshold = spec.threshold
    row.timeout_ms = spec.timeout_ms
    row.fail_mode = spec.fail_mode
    row.auth_header = spec.auth_header
    if secret_ciphertext is not None:
        row.auth_secret_encrypted = secret_ciphertext
    elif clear_secret or not spec.auth_header:
        row.auth_secret_encrypted = None
    row.enabled = spec.enabled
    session.flush()
    operator_log.record(
        session,
        "operator.custom_model.saved",
        actor=actor,
        reason=reason or f"model '{spec.key}' {'updated' if before else 'registered'}",
        subject_type="custom_model",
        subject_id=row.id,
        before=before,
        after=_audit_json(row),
    )
    if spec.entity_prefix == "CUSTOM" or (before and before.get("entity_prefix") == "CUSTOM"):
        sync_policy(session, actor=actor, seed={f"custom.{spec.key}": {"effect": effect}})
    return row


def set_model_enabled(
    session: Session, key: str, enabled: bool, *, actor: str, reason: str = ""
) -> CustomModel | None:
    from agentfox.capabilities.detection.custom_store import sync_policy

    row = get_model(session, key)
    if row is None:
        return None
    before = row.enabled
    row.enabled = enabled
    session.flush()
    operator_log.record(
        session,
        "operator.custom_model.toggled",
        actor=actor,
        reason=reason or f"model '{key}' {'on' if enabled else 'off'}",
        subject_type="custom_model",
        subject_id=row.id,
        before={"enabled": before},
        after={"enabled": enabled},
    )
    if row.entity_prefix == "CUSTOM":
        sync_policy(session, actor=actor)
    return row


def delete_model(session: Session, key: str, *, actor: str) -> bool:
    from agentfox.capabilities.detection.custom_store import sync_policy

    row = get_model(session, key)
    if row is None:
        return False
    was_custom = row.entity_prefix == "CUSTOM"
    operator_log.record(
        session,
        "operator.custom_model.deleted",
        actor=actor,
        reason=f"model '{key}' removed",
        subject_type="custom_model",
        subject_id=row.id,
        before=_audit_json(row),
    )
    session.delete(row)
    session.flush()
    if was_custom:
        sync_policy(session, actor=actor)
    return True
