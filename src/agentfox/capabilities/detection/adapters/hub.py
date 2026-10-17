"""Loading a Guardrails AI validator class, with their telemetry switched off.

Used by `rails.guardrails_ai`, which runs validators from an installed
`guardrails-ai` package as one Guard. The individual Hub validators that used to be
wrapped here one detector each (`rails.hub.*`) are now ported natively into
`detection/validators/`, so none of them needs a separate install.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _silence_guardrails_telemetry() -> None:
    """Stop Guardrails AI phoning home before any validator runs.

    Found by running this adapter against the real package: importing a Hub
    validator starts an OpenTelemetry exporter that POSTs spans to a third-party
    endpoint (an AWS API Gateway host), and `RC.enable_metrics` defaults to True
    with no environment override — the only way to turn it off is a
    `~/.guardrailsrc` file the operator has to know to write.

    That is not a defect in their project; it is a reasonable default for a
    library. It is intolerable here. This product's first README line is that it
    runs offline with no egress, `AGENTFOX_ALLOW_EGRESS` defaults to false, and
    the whole argument for self-hosting a governance tool is that it does not
    quietly talk to anyone. A control plane that starts exporting telemetry to a
    third party the moment somebody enables a PII check would be breaking its own
    promise, on a page that advertises the promise.

    So it is switched off unconditionally rather than behind our own egress
    setting: allowing egress means our operator chose to let *this product* reach
    a model provider they configured, not to let a transitive dependency report
    on them. Best-effort — their internals have moved between versions, and
    failing to silence telemetry must not take the detector down with it.
    """
    try:
        from guardrails import settings  # type: ignore

        settings.disable_tracing = True
        rc = getattr(settings, "rc", None)
        if rc is not None:
            rc.enable_metrics = False
            # Belt to that braces: the hosted inferencing they are retiring in
            # August 2026 is another way a validator reaches the network.
            if hasattr(rc, "use_remote_inferencing"):
                rc.use_remote_inferencing = False
    except ModuleNotFoundError:
        # Not installed is the normal state, not a problem to warn about. This
        # warned on every start of every deployment that does not have it.
        return
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        log.warning("could not disable guardrails-ai telemetry: %s", exc)

    _detach_hub_telemetry_exporter()


def _detach_hub_telemetry_exporter() -> None:
    """Take the network out of their telemetry pipeline, not just the flag.

    The flags above stopped being sufficient. Measured against guardrails-ai
    0.11.0 with a real Hub validator, spans still went out — the setting suppresses
    nothing here because `HubTelemetry.initialize_tracer` builds its
    `BatchSpanProcessor(OTLPSpanExporter(endpoint="https://…execute-api.
    us-east-1.amazonaws.com/v1/traces"))` *unconditionally*; `enabled` only gates
    whether spans are created afterwards, and `HubTelemetry` is a singleton, so
    whichever code path constructs it first decides for the whole process.

    So this claims the singleton before their code can, and then removes the
    exporter behind it — anything that does create a span writes into a sink
    that goes nowhere. The flag is still set above, because two independent
    reasons for no egress is the right number when the promise is "no egress".

    Best-effort by design, same as the rest of this function: their internals
    have moved between versions, and failing to silence telemetry must not take
    the detector down with it. What it must never do is fail *silently* — a
    warning naming the endpoint is the minimum an operator needs to decide
    whether to keep the validator.
    """

    class _Nowhere:
        """An OTel SpanExporter that exports to nothing."""

        def export(self, _spans: Any) -> Any:
            from opentelemetry.sdk.trace.export import SpanExportResult

            return SpanExportResult.SUCCESS

        def force_flush(self, timeout_millis: int = 0) -> bool:
            return True

        def shutdown(self) -> None:
            return None

    try:
        from guardrails.utils import hub_telemetry_utils as telemetry  # type: ignore

        # Constructing it with enabled=False claims the singleton; if theirs is
        # already built, this returns that one and we defuse it in place.
        telemetry.HubTelemetry(enabled=False)
        instance = getattr(telemetry.HubTelemetry, "_instance", None)
        if instance is None:
            return
        instance._enabled = False
        processor = getattr(instance, "_processor", None)
        exporter = getattr(processor, "span_exporter", None)
        if exporter is None:
            return
        try:
            processor.span_exporter = _Nowhere()  # type: ignore[misc]
            return
        except AttributeError:
            # `span_exporter` is a read-only property on BatchSpanProcessor in
            # current opentelemetry-sdk, and which private attribute backs it has
            # moved between releases. Neutering the exporter object itself needs
            # no knowledge of that: whoever holds it, it no longer has a network
            # call in it.
            pass
        nowhere = _Nowhere()
        exporter.export = nowhere.export  # type: ignore[method-assign]
        exporter.force_flush = nowhere.force_flush  # type: ignore[method-assign]
        exporter.shutdown = nowhere.shutdown  # type: ignore[method-assign]
    except ModuleNotFoundError:
        return
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        # Loud on purpose when the package IS there: the operator needs to know
        # the egress promise is not being kept before deciding to keep using it.
        log.warning(
            "could not detach guardrails-ai hub telemetry; it may export spans to "
            "their endpoint (%s)",
            exc,
        )


def _load_validator_class(slug: str) -> type | None:
    """Find the Validator subclass in a hub validator's module.

    Tries the standalone package first (`guardrails_ai.<slug>`, the form their
    README now documents) and falls back to the classic namespace
    (`guardrails.hub`). Returns None if neither is installed — which is the
    normal state, not an error.
    """
    # Before anything of theirs is imported or constructed — which is what this
    # comment always said, two lines below where it was true. `from
    # guardrails.validator_base import ...` pulls in the whole package and lets
    # its telemetry singleton be built first, and a singleton built first wins.
    _silence_guardrails_telemetry()

    try:
        from guardrails.validator_base import Validator  # type: ignore
    except Exception:
        return None

    module = None
    standalone = False
    for name in (f"guardrails_ai.{slug}", "guardrails.hub"):
        try:
            module = __import__(name, fromlist=["*"])
            standalone = name != "guardrails.hub"
            break
        except Exception:
            continue
    if module is None:
        return None

    # Match on the slug: "detect_jailbreak" -> "DetectJailbreak",
    # case-insensitively, which also catches the acronym spellings (NSFWText,
    # ValidSQL) that a naive title-case would miss.
    want = slug.replace("_", "").lower()
    candidates = []
    for attr in dir(module):
        obj = getattr(module, attr, None)
        if isinstance(obj, type) and issubclass(obj, Validator) and obj is not Validator:
            candidates.append(obj)
            if attr.replace("_", "").lower() == want:
                return obj

    # A lone unnamed candidate is only safe in the standalone package, where the
    # module IS this validator and the class is simply spelled unexpectedly.
    #
    # `guardrails.hub` is a shared, lazily-populated namespace: it exports
    # nothing until something is installed, and then exports whatever is. So
    # this fallback, applied there, returned *somebody else's* validator for any
    # slug that was not installed. Measured with one hub package present:
    #
    #   unusual_prompt   -> DetectJailbreak
    #   bias_check       -> DetectJailbreak
    #   nsfw_text        -> DetectJailbreak
    #   competitor_check -> DetectJailbreak
    #
    # Four detectors, each with its own key, its own entity type, its own
    # measured precision and its own policy rules, all running the jailbreak
    # classifier. A governance control reporting the wrong check under the right
    # name is worse than one that is off, because nothing about it looks wrong.
    if standalone and len(candidates) == 1:
        return candidates[0]
    return None
