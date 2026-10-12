"""The Guardrails AI Hub adapter, against a stand-in for their package.

Guardrails AI is an optional dependency and its Hub validators are sixty-five
separate packages with their own licences, several of which download model
weights on first use. None of that belongs in CI. What does belong is the part
we wrote: finding the validator class in a module, telling a pass from a fail,
mapping the fail onto our taxonomy, redacting the message, and refusing to
report a thrown validator as a clean pass.

So these build a module shaped like theirs — `Validator` base,
`PassResult`/`FailResult`, a `guardrails_ai.<slug>` submodule — and point the
adapter at it. If Guardrails renames something, `available()` goes False and the
detector reads "not installed", which is the safe direction; these tests pin the
behaviour on the side we control.
"""

from __future__ import annotations

import sys
import types

import pytest

from agentfox.capabilities.detection.adapters.hub import _load_validator_class


class _Validator:
    """Stands in for guardrails.validator_base.Validator."""


class PassResult:
    """Named as theirs is: the adapter reads the shape AND the name."""


class FailResult:
    def __init__(self, error_message: str) -> None:
        self.error_message = error_message


@pytest.fixture
def fake_guardrails(monkeypatch):
    """Install a minimal `guardrails` + `guardrails_ai.<slug>` into sys.modules."""

    base = types.ModuleType("guardrails.validator_base")
    base.Validator = _Validator
    root = types.ModuleType("guardrails")
    root.validator_base = base
    monkeypatch.setitem(sys.modules, "guardrails", root)
    monkeypatch.setitem(sys.modules, "guardrails.validator_base", base)

    ns = types.ModuleType("guardrails_ai")
    monkeypatch.setitem(sys.modules, "guardrails_ai", ns)

    def install(slug: str, class_name: str, behaviour):
        mod = types.ModuleType(f"guardrails_ai.{slug}")

        class Made(_Validator):
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def validate(self, value, metadata):
                return behaviour(value)

        Made.__name__ = class_name
        setattr(mod, class_name, Made)
        # A real module also exports the things it imported; the discovery has to
        # pick the right one out of that, not just take the only class it finds.
        mod.Validator = _Validator
        monkeypatch.setitem(sys.modules, f"guardrails_ai.{slug}", mod)
        setattr(ns, slug, mod)
        return Made

    return install


def test_the_validator_class_is_found_by_slug_not_by_being_the_only_one(fake_guardrails):
    fake_guardrails("detect_jailbreak", "DetectJailbreak", lambda v: PassResult())
    assert _load_validator_class("detect_jailbreak").__name__ == "DetectJailbreak"


def test_acronym_class_names_are_matched(fake_guardrails):
    """`nsfw_text` -> `NSFWText`, which a naive title-case would miss."""
    fake_guardrails("nsfw_text", "NSFWText", lambda v: PassResult())
    assert _load_validator_class("nsfw_text").__name__ == "NSFWText"


def test_guardrails_telemetry_is_switched_off_before_a_validator_loads(monkeypatch):
    """Enabling a Hub validator must not start exporting spans to a third party.

    Found by running this adapter against the real package: importing a Hub
    validator starts an OpenTelemetry exporter that POSTs to an AWS API Gateway
    host, and `RC.enable_metrics` defaults to True with no environment override.

    This product's first README line is that it runs offline with no egress, and
    `AGENTFOX_ALLOW_EGRESS` defaults to false. A control plane that quietly
    reports to a third party the moment somebody switches on a PII check is
    breaking its own promise, so this is not optional and not behind a setting.
    """
    import sys
    import types

    from agentfox.capabilities.detection.adapters.hub import _silence_guardrails_telemetry

    class _RC:
        enable_metrics = True
        use_remote_inferencing = True

    fake_settings = types.SimpleNamespace(disable_tracing=None, rc=_RC())
    root = types.ModuleType("guardrails")
    root.settings = fake_settings
    monkeypatch.setitem(sys.modules, "guardrails", root)

    _silence_guardrails_telemetry()

    assert fake_settings.disable_tracing is True
    assert fake_settings.rc.enable_metrics is False
    assert fake_settings.rc.use_remote_inferencing is False


def test_silencing_telemetry_never_takes_the_detector_down(monkeypatch):
    """Their internals move between versions; failing to silence must not raise."""
    import sys

    from agentfox.capabilities.detection.adapters.hub import _silence_guardrails_telemetry

    broken = object()  # no `.settings`, no `.rc`
    monkeypatch.setitem(sys.modules, "guardrails", broken)
    _silence_guardrails_telemetry()  # must not raise


# ---------------------------------------------------------------------------
# Found by installing the real packages into a scratch venv and looking at the
# validators that were NOT installed. None of this is reachable with the
# stand-in alone, so each test reproduces the shape the real packages have.
# ---------------------------------------------------------------------------


@pytest.fixture
def shared_hub_namespace(monkeypatch):
    """`guardrails.hub` as it really behaves: shared, and lazily populated.

    It exports nothing until a hub package is installed, and then exports that
    package's class — not the one you asked for.
    """
    base = types.ModuleType("guardrails.validator_base")
    base.Validator = _Validator
    root = types.ModuleType("guardrails")
    root.validator_base = base
    hub = types.ModuleType("guardrails.hub")

    class DetectJailbreak(_Validator):
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def validate(self, value, metadata):
            return PassResult()

    hub.DetectJailbreak = DetectJailbreak
    root.hub = hub
    monkeypatch.setitem(sys.modules, "guardrails", root)
    monkeypatch.setitem(sys.modules, "guardrails.validator_base", base)
    monkeypatch.setitem(sys.modules, "guardrails.hub", hub)
    monkeypatch.delitem(sys.modules, "guardrails_ai", raising=False)
    return DetectJailbreak


def test_an_uninstalled_slug_never_resolves_to_somebody_elses_validator(shared_hub_namespace):
    """The worst thing this adapter could do, and it was doing it.

    With one hub package installed, `guardrails.hub` holds exactly one class, so
    the "lone candidate" fallback handed that class to every slug that asked.
    Measured against the real packages: unusual_prompt, bias_check, nsfw_text
    and competitor_check all resolved to DetectJailbreak. Each would have run
    the jailbreak classifier while reporting its own entity type, under its own
    key, with its own measured precision and its own policy rules. A control
    reporting the wrong check under the right name is worse than one that is
    off, because nothing about it looks wrong.
    """
    for slug in ("unusual_prompt", "bias_check", "nsfw_text", "competitor_check"):
        assert _load_validator_class(slug) is None, slug


def test_the_slug_that_is_installed_still_resolves(shared_hub_namespace):
    """The fix must not cost the classic namespace its one legitimate use."""
    assert _load_validator_class("detect_jailbreak") is shared_hub_namespace


def test_a_lone_class_is_still_accepted_from_the_standalone_package(fake_guardrails):
    """There the module IS the validator, so an unexpected spelling is safe."""
    made = fake_guardrails("bias_check", "SomethingRenamed", lambda v: PassResult())
    del sys.modules["guardrails_ai.bias_check"].Validator  # the only class left
    assert _load_validator_class("bias_check") is made
