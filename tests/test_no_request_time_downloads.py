"""No detector fetches anything from the network on a guarded request.

`adapters/classifiers.py` has had the rule, and the comment for it, since it was
written: "NFR-4/NFR-9: never trigger a download at request time. Absent weights
mean 'unavailable', not 'fetch it now'." It checks the Hugging Face cache in
`available()` and reports itself off when the weights are not there.

`adapters/presidio.py` did not. `available()` returned True the moment
`presidio_analyzer` imported, and `AnalyzerEngine()` is built lazily on the
first real request. Measured on a clean install of `agentfox[pii]`:

    available(): True
    detect():    downloaded en_core_web_lg (400.7 MB), returned in 29,791ms

A 400MB `pip install` from inside a guarded request, against a 300ms pre-flight
budget and a 40ms per-detector timeout, with `allow_egress` false — that setting
gates our own outbound calls and never saw this one. Air-gapped, the same
`available(): True` was followed by every request raising a ProxyError against
raw.githubusercontent.com, so the Detectors strip reported PII as covered by a
check that could not run.

These tests state the rule as a property of the whole registry rather than of
one adapter, so the next wrapped dependency with a lazy download inherits it.
"""

from __future__ import annotations

import pytest

from agentfox.guardrails import all_detectors
from agentfox.guardrails.adapters.presidio import PresidioPiiDetector

#: Detectors backed by something downloadable. Each must decide `available()`
#: from what is already on disk — never by fetching, and never by assuming.
PROVISIONED = ("pii.presidio", "injection.classifier", "safety.granite", "safety.restricted")


@pytest.mark.parametrize("key", PROVISIONED)
def test_a_detector_backed_by_a_download_checks_the_disk_first(key):
    """`available()` must not be answerable by "the library imported".

    The check is structural on purpose: asserting the measured behaviour would
    need the real 400MB model in CI, and what actually went wrong was that one
    adapter had no disk check at all.
    """
    detector = all_detectors()[key]
    has_check = any(
        hasattr(detector, name)
        for name in ("_model_present", "_weights_present")
    )
    assert has_check, (
        f"{key} is backed by a downloadable asset and has no method that asks "
        "whether it is already on disk, so `available()` can only be answering "
        "from the import. That is how a 400MB download ended up inside a "
        "request."
    )


def test_presidio_is_unavailable_when_its_model_is_not_installed(monkeypatch):
    monkeypatch.setattr(PresidioPiiDetector, "_model_present", staticmethod(lambda: False))
    assert PresidioPiiDetector().available() is False


def test_presidio_is_available_once_the_model_is_there(monkeypatch):
    """The fix must not simply switch the detector off."""
    monkeypatch.setitem(__import__("sys").modules, "presidio_analyzer", object())
    monkeypatch.setattr(PresidioPiiDetector, "_model_present", staticmethod(lambda: True))
    assert PresidioPiiDetector().available() is True


def test_the_reason_names_the_command_that_fixes_it(monkeypatch):
    """"unavailable" without the fix is just a dead end in the UI."""
    monkeypatch.setattr(PresidioPiiDetector, "_model_present", staticmethod(lambda: False))
    reason = PresidioPiiDetector().unavailable_reason
    assert "python -m spacy download en_core_web_lg" in reason
    # And says why it is not simply fetched, so it does not read as a bug.
    assert "guarded request" in reason


def test_a_missing_package_and_a_missing_model_are_different_reasons(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "presidio_analyzer", None)
    assert "not installed" in PresidioPiiDetector().unavailable_reason


def test_warm_does_not_build_the_engine_when_the_model_is_absent(monkeypatch):
    """`warm_all()` runs at process startup. Building the engine there would move

    the download from the first request to boot — better, but still a download
    nobody asked for, and still egress from a deployment that declared none.
    """
    built = []
    monkeypatch.setattr(
        "agentfox.guardrails.adapters.presidio._analyzer", lambda: built.append(1)
    )
    monkeypatch.setattr(PresidioPiiDetector, "_model_present", staticmethod(lambda: False))
    PresidioPiiDetector().warm()
    assert built == []

    monkeypatch.setattr(PresidioPiiDetector, "_model_present", staticmethod(lambda: True))
    PresidioPiiDetector().warm()
    assert built == [1]
