"""Does a deny on this (harness, event) actually stop the agent?

The question nothing in this product asked. We assert enforcement across nine
surfaces and several integrations, and `langgraph.py` does raise on a block —
but nothing recorded, per integration and per event, whether the verdict is
read at a call site that prevents the action. That is a different claim from
"we returned block", and only one of them is a control.

A competitor learned this the expensive way. Their docs described a harness's
turn-end hook as a working gate while upstream discarded the return value, so
every customer policy on that event enforced nothing, silently, for months.
Prose drifted; a table a test can assert against cannot.

**ABSENT MEANS UNVERIFIED, NOT "BLOCK".** A caller must treat a missing entry
as "say nothing". A hedge rendered in the UI is still a claim, and an
unverified claim is what this file exists to prevent.

Every row carries how it was established:

    SOURCE      read in the harness's own source or shipped bundle
    VENDOR_DOCS the vendor documents the behaviour
    LIVE_PROBE  we ran it and watched what happened

and the version it was established against, because a version is part of the
claim and not a footnote. A row whose version has moved is due for a re-probe;
it is not evidence.

**Why there is one row and not twelve.** Because one harness has been probed.
Writing down what the others probably do — from memory, from a blog post, from
what would be sensible — is exactly the failure above with a fresh coat on it.
Rows arrive when somebody runs the probe, and the probe is cheap: install a
hook that denies one sentinel string and allows everything else, then try the
sentinel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: What a deny does on this event, where we know.
Capability = Literal["block", "observe"]

#: How a row was established. Ordered weakest to strongest.
Evidence = Literal["VENDOR_DOCS", "SOURCE", "LIVE_PROBE"]


@dataclass(frozen=True)
class Verified:
    """One (harness, event) pair we have actually established something about."""

    capability: Capability
    evidence: Evidence
    #: The harness version this was established against. Part of the claim.
    version: str
    #: Where to look to check it again — a file and symbol, a docs URL, or the
    #: probe that produced it.
    reference: str
    note: str = ""


#: The table. Keyed (harness, event).
#:
#: Empty is the correct state for a harness nobody has probed, and it is not a
#: placeholder to be filled in with plausible values. `agentfox admin hooks install`
#: reads this and tells the operator plainly when it cannot promise
#: enforcement, which is better than installing a hook that reports itself as
#: a gate.
CAPABILITY: dict[tuple[str, str], Verified] = {
    # ── claude ────────────────────────────────────────────────────────────
    # Established by running it, in a Claude Code session, against a hook
    # installed for that session. The probe denied one sentinel string and
    # allowed everything else, so the session stayed usable while the deny
    # path was exercised for real.
    ("claude", "PreToolUse"): Verified(
        capability="block",
        evidence="LIVE_PROBE",
        version="2.1.220",
        reference="probe: hookSpecificOutput.permissionDecision='deny' on a Bash call",
        note=(
            "The call did not run and `permissionDecisionReason` was surfaced to the "
            "agent verbatim. Cross-checks against the shipped bundle: the PreToolUse "
            "schema is hookSpecificOutput{hookEventName, permissionDecision, "
            "permissionDecisionReason, updatedInput, additionalContext}, and "
            "permissionDecision accepts allow|deny|ask|defer — `defer` is print-mode "
            "only and is ignored with a warning in an interactive session."
        ),
    ),
    # Established by running it, in this session, at high effort under the
    # `auto` permission mode. A PostToolUse hook returned `decision: "block"`
    # with a reason AND an `additionalContext`, on a Bash call whose command
    # echoed a sentinel.
    #
    # **The command ran.** Its stdout came back as the tool result in the
    # same turn, alongside the hook's reason. So the harness calls this
    # "blocking" and it does not stop anything: by the time PostToolUse
    # fires, the side effect has happened. That is the exact distinction this
    # table exists to record, and it is why this row says `observe` while the
    # harness's own vocabulary says block.
    ("claude", "PostToolUse"): Verified(
        capability="observe",
        evidence="LIVE_PROBE",
        version="2.1.220",
        reference="probe: decision='block' on a Bash PostToolUse; stdout still returned",
        note=(
            "The call had already run and its result reached the model regardless. What "
            "a refusal here does buy is real but smaller: both `reason` and "
            "`hookSpecificOutput.additionalContext` were surfaced to the agent verbatim "
            "in the same turn, so the model is told the result it is holding is "
            "untrusted before it acts on it. Payload adds `tool_response` and "
            "`duration_ms` to the PreToolUse shape. Treat this event as the place to "
            "catch indirect injection arriving, never as containment."
        ),
    ),
    # Not probed: UserPromptSubmit fires when the *operator* submits a turn,
    # which a hook running inside somebody else's turn cannot trigger. So
    # this row is SOURCE, and the source is the consumer rather than the
    # docs, because the docs only say `decision: "block"` is "for"
    # UserPromptSubmit and that is not the same as saying what it does.
    ("claude", "UserPromptSubmit"): Verified(
        capability="block",
        evidence="SOURCE",
        version="2.1.220",
        reference=(
            "bundle: executeUserPromptSubmitHooks consumer, `shouldQuery:!1` on blockingError"
        ),
        note=(
            "On a blocking result the consumer returns `shouldQuery: false` — the turn "
            "is never sent to the model — and renders "
            "`UserPromptSubmit operation blocked by hook: <reason>`. `suppressOriginalPrompt` "
            "decides whether the operator's own text is echoed back beside it. A "
            "non-blocking hook's `additionalContext` is attached to the turn instead. "
            "Re-probe this the first time a real operator turn runs through it; SOURCE "
            "is weaker than LIVE_PROBE and this row should not stay SOURCE forever."
        ),
    ),
}

#: What each event is a checkpoint *on*. A hook event is not a surface — it is
#: a moment — and the mapping between them is the thing a reader gets wrong.
#: PreToolUse sees arguments about to be used; PostToolUse sees a result
#: arriving, which is the canonical indirect-injection vector; UserPromptSubmit
#: sees the operator's own words, the one genuinely untrusted-but-authorised
#: input in the session.
EVENT_SURFACE: dict[tuple[str, str], str] = {
    ("claude", "PreToolUse"): "tool_args",
    ("claude", "PostToolUse"): "tool_result",
    ("claude", "UserPromptSubmit"): "input",
}

#: Ways to say no, where more than one works. Recorded separately because
#: which one to EMIT is a different question from whether the event blocks,
#: and picking the wrong one is how a hook reports itself as a gate while
#: enforcing nothing.
#:
#: Both of these were probed on claude 2.1.220 and both block. We emit the
#: structured decision: exit 2 sends the reason through stderr, which the
#: harness prefixes with the script's own path, so the operator reads
#: "[/path/to/hook.sh]: <reason>" instead of the reason. The structured form
#: surfaces it clean.
BLOCKING_MECHANISM: dict[str, str] = {
    "claude": "hookSpecificOutput.permissionDecision",
}

#: Harnesses whose hook may REWRITE a tool call rather than only allow or
#: refuse it. This is the one that changes what the product can do rather than
#: how it reports: an `alter` verdict — strip the secret from the argument, add
#: the missing WHERE clause — becomes enforceable at the hook instead of being
#: downgraded to a block.
#:
#: Probed: returning `updatedInput: {"command": "echo REWRITTEN_BY_HOOK"}` with
#: permissionDecision `allow` ran the hook's command and not the agent's.
CAN_REWRITE_INPUT: dict[str, Verified] = {
    "claude": Verified(
        capability="block",
        evidence="LIVE_PROBE",
        version="2.1.220",
        reference="probe: hookSpecificOutput.updatedInput replaced the Bash command",
        note="The rewritten command ran in place of the one the model asked for.",
    ),
}


#: What a deny actually prevents, per event, in the reader's noun.
_STOPS = {
    "PreToolUse": "stops the call before it runs",
    "PostToolUse": "does not stop anything; the call has already run",
    "UserPromptSubmit": "stops the turn reaching the model",
}


def capability_of(harness: str, event: str) -> Verified | None:
    """What a deny does here, or None if nobody has checked."""
    return CAPABILITY.get((harness, event))


def describe(harness: str, event: str) -> str:
    """One line an operator can act on, for the install summary and `doctor`."""
    known = capability_of(harness, event)
    if known is None:
        return (
            f"{harness}/{event}: unverified. The hook will run and record, and whether a "
            "deny stops the call has not been established against this harness — treat it "
            "as observation until it has."
        )
    provenance = f"({known.evidence.lower()}, {known.version})"
    # The noun matters. "A deny stops the call" is wrong on an event that
    # never sees a call, and "observes only" understates an event that does
    # reach the model. Each event gets the sentence that is true of it.
    if known.capability == "block":
        stops = _STOPS.get(event, "stops the action")
        return f"{harness}/{event}: a deny {stops} {provenance}."
    if event == "PostToolUse":
        return (
            f"{harness}/{event}: the call has already run — a deny cannot withdraw it, "
            f"but the reason does reach the model {provenance}."
        )
    return (
        f"{harness}/{event}: the action proceeds regardless; this event observes only {provenance}."
    )
