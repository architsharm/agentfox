"""The convenience surfaces: content, the conversation window, memory writes,
completions, reasoning, files and inter-agent messages, each a thin call into
`evaluate()` with the right surface and evidence.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from agentfox.containment.agent_messaging import verify_message
from agentfox.core.crypto import DecryptionFailed, decrypt_secret
from agentfox.core.models import (
    Agent,
    AgentMessageLog,
    AgentSigningKey,
    Identity,
    MemoryEntry,
    Trace,
    utcnow,
)
from agentfox.detection import TaintTracker
from agentfox.runtime.enforcement.result import EnforcementResult
from agentfox.runtime.enforcement.rules import _VERDICT_RANK, _fired_rule


class _SurfacesMixin:
    """Enforcer's convenience surfaces. Mixed into :class:`Enforcer`, never used alone."""

    def check_content(
        self,
        agent_slug: str,
        content: str,
        surface: str = "input",
        taint_source: str = "user",
        persist: bool = True,
        trace: Trace | None = None,
    ) -> dict[str, Any]:
        """Light single-surface check. Used by the red-team runner and `/v1/guard`.

        `trace` is optional because the red-team runner has no trace to attach to and
        wants none: a simulated attack is not something the agent did. Every caller on
        the live path passes one, which is what puts a governed request on the Traces
        page and into the control telemetry.
        """
        if persist:
            # The live path — SDK `check()`, `/v1/guard/*`: an unknown slug is shadow
            # traffic and is registered as such, the same as every other guard. Looked
            # up without registering, a finding about it was filed under `agent:None`.
            agent, identity, _shadow = self.resolve(agent_slug)
        else:
            # A dry run (red team, MCP preview) is not something an agent did and must
            # not create one.
            agent = self.session.scalar(select(Agent).where(Agent.slug == agent_slug))
            identity = (
                self.session.scalar(select(Identity).where(Identity.agent_id == agent.id))
                if agent
                else None
            )
        tracker = TaintTracker()
        tracker.mark("$.content", taint_source, content)
        result = self.evaluate(
            agent=agent,
            identity=identity,
            content=content,
            surface=surface,
            taint_source=taint_source,
            tracker=tracker,
            persist=persist,
            trace=trace,
        )
        return result.to_json()

    def check_conversation_window(
        self,
        *,
        agent_slug: str,
        session_id: str,
        new_user_text: str,
        window: int = 6,
        trace: Trace | None = None,
    ) -> EnforcementResult:
        """Tier A — payload-splitting / multi-turn jailbreak defense.

        Every other detection path in this file evaluates one message (`evaluate`)
        or one tool call (`guard_tool_call`) in isolation. That is a real, named gap:
        an attacker can split a payload across several turns — each individually
        innocuous — that only reads as an attack once assembled ("payload
        splitting", OWASP LLM01; see also Microsoft's "Crescendo" multi-turn
        jailbreak, arXiv:2404.01833, which escalates gradually rather than splitting
        a single payload but defeats per-message evaluation the same way). Found by
        actually checking: neither `autoguard.py`'s `_govern` (joins one call's own
        `messages` array, but never a previous *separate* call) nor the gateway's
        `preflight` (loops per-message, never joins) re-evaluates content against
        conversation history.

        This closes it using the substrate that already exists for a different
        reason — `ConversationTurn`, written by escalation governance — by
        joining the last `window` turns' `user_text` with the new message and
        running the same detector pipeline over the assembled text. Requires the
        caller to supply a stable `session_id` across turns (the same requirement
        `record_turn` already has); without one, this degrades to evaluating the
        new message alone, harmlessly.

        **Two different multi-turn attacks are checked here, by two different
        mechanisms.** Joining is the right answer to payload splitting and the wrong
        answer to a crescendo, and `benchmarks/crescendo/` measured the difference
        rather than assuming it: 0 of 13 gradual-escalation conversations were caught
        at any turn index, because joining six innocuous turns produces six innocuous
        turns and there is no hidden string to reassemble. So the same window is also
        handed to the trajectory scorer (`trajectory.py`) as a *sequence* rather
        than a join, which measures the slope of a risk-adjacent score instead of the
        content of the concatenation. The joined-text verdict is what this method
        returns; the trajectory finding rides along on `result.taint["trajectory"]`
        and on the `action["risks"]` channel, observe-first — see `_trajectory_checks`.
        """
        from agentfox.core.models import ConversationTurn

        agent, identity, _ = self.resolve(agent_slug)
        prior = list(
            reversed(
                self.session.scalars(
                    select(ConversationTurn)
                    .where(ConversationTurn.session_id == session_id)
                    .order_by(ConversationTurn.turn_index.desc())
                    .limit(window)
                ).all()
            )
        )
        texts = [t.user_text for t in prior if t.user_text] + [new_user_text]
        joined = "\n".join(texts)
        return self.evaluate(
            agent=agent,
            identity=identity,
            content=joined,
            surface="input",
            trace=trace,
            conversation_window=texts,
        )

    def guard_memory_write(
        self,
        *,
        agent_slug: str,
        content: str,
        subject: str | None = None,
        taint_source: str = "user",
        provenance: dict[str, Any] | None = None,
        verified_by: str | None = None,
        ttl_seconds: int | None = None,
        trace: Trace | None = None,
        credential: str | None = None,
        persist: bool = True,
    ) -> EnforcementResult:
        """Authorise a write into an agent's long-term memory before it commits.

        A write into a vector store, a `mem0`-style store, or a LangGraph
        checkpointer is governed the same way a tool call is — the detector
        pipeline runs on the way *in*, not only at retrieval time, so a poisoned
        entry that would be blocked on the way out never gets the chance to
        persist on the way in.

        Provenance is carried on the entry itself so a later retrieval can weight
        or refuse it the way retrieval already weights a source tier. An entry nobody
        has verified (``verified_by=None``) defaults **closed**: it decays after
        ``ttl_seconds`` (default: ``settings.memory_unverified_ttl_seconds``)
        rather than persisting indefinitely — the opposite default from
        :class:`Suppression`, deliberately, because an unconfirmed memory has not
        earned the benefit of the doubt a human-authored suppression has.
        """
        agent, identity, _ = self.resolve(agent_slug, credential)
        result = self.evaluate(
            agent=agent,
            identity=identity,
            content=content,
            surface="memory_write",
            trace=trace,
            taint_source=taint_source,
            # The entry about to be written, checked against the principal the
            # caller declared in `evidence`. An entry with no subject is the dangerous
            # case rather than the safe one — it was written by someone, about someone,
            # and nothing records who.
            memory_entry={
                "key": str((provenance or {}).get("key") or ""),
                "subject": subject,
                "session": (provenance or {}).get("session"),
                "durable": verified_by is not None,
            },
            persist=persist,
        )
        # Mode-aware, like every other surface (nothing blocks until a
        # policy is promoted to enforce) — `result.verdict`, not the
        # `effective_verdict` counterfactual, is what actually gates the
        # write. Once enforced, a blocked or escalated write does not get to
        # persist at all: that is the entire point of governing the write
        # path rather than only the read path. tokenize/mask/redact still
        # persist, but the *redacted* content (`result.content` is only set
        # when the verdict rewrote it), matching every other surface.
        if persist and result.verdict not in ("block", "escalate", "abstain"):
            expires_at = None
            if verified_by is None:
                ttl = (
                    ttl_seconds
                    if ttl_seconds is not None
                    else self.settings.memory_unverified_ttl_seconds
                )
                expires_at = utcnow() + dt.timedelta(seconds=ttl)
            entry = MemoryEntry(
                agent_id=agent.id if agent else None,
                subject=subject,
                content=result.content if result.content is not None else content,
                taint_source=taint_source,
                provenance=provenance or {},
                decision_id=result.decision_id,
                verified_by=verified_by,
                expires_at=expires_at,
            )
            self.session.add(entry)
            self.session.flush()
            result.taint["memory_entry_id"] = entry.id
            result.taint["memory_expires_at"] = expires_at.isoformat() if expires_at else None
        return result

    def guard_completion(
        self,
        *,
        agent_slug: str,
        claim: str = "",
        completion: dict[str, Any] | None = None,
        trace: Trace | None = None,
        credential: str | None = None,
        persist: bool = True,
    ) -> EnforcementResult:
        """Decide whether the agent is allowed to stop.

        Every other guard on this class asks whether an action is safe. This one
        asks a question nobody was asking: the agent says it is finished — is it?

        The gap this closes is `c4` in the market survey, "did the agent finish
        the task it was given", which the evaluation vendors score after the
        fact on sampled runs and nobody gates at runtime. We had the same shape:
        `silent_failure` is an offline scorer, so an agent that reported "your
        refund is processed" after the payment API returned an error was caught
        in a report next week, not stopped at the time.

        The division of labour is the important part. The **caller** reports
        what it can observe at the moment of the claim — `{"committed": True,
        "ci_green": False}` — because only the caller can see it. **Policy**
        decides which of those must hold, through `completion_requires`, because
        that is a governance decision and it differs per agent and per
        environment. A condition the caller never mentions counts as unmet
        rather than assumed: an agent claiming to be done has to have been
        checked, and a caller that forgot to report `ci_green` did not check it.

        The claim text goes through the detector pipeline like any other output,
        so a false claim of success is also subject to the content rules that
        already exist — this adds the gate, it does not replace them.
        """
        agent, identity, _ = self.resolve(agent_slug, credential)
        return self.evaluate(
            agent=agent,
            identity=identity,
            content=claim,
            surface="completion",
            trace=trace,
            completion=completion or {},
            persist=persist,
        )

    def guard_reasoning(
        self,
        *,
        agent_slug: str,
        content: str,
        intent: str | None = None,
        taint_source: str = "tool_result",
        trace: Trace | None = None,
        credential: str | None = None,
        persist: bool = True,
    ) -> EnforcementResult:
        """Check the model's reasoning before it acts on it.

        This is the surface that separates *an injection arrived* from *an
        injection landed*. `retrieved` and `tool_result` see a payload entering
        the context; nothing saw whether the model took it up. By the time a
        tool call exists the goal substitution has already happened, and taint
        tracking can say the argument came from untrusted content without ever
        saying the agent changed its mind.

        So a detection here is weighted differently from the same detection
        anywhere else, and the shipped rule says so: injection-shaped text in a
        retrieved document is an attempt, and the same text in the model's own
        reasoning is a compromise in progress. That is the whole argument for
        the surface existing, and it is why `taint_source` defaults to
        `tool_result` rather than `user` — reasoning is derived content, never
        something the operator typed.

        Honest about what it is not. This reads reasoning the caller hands over;
        it cannot see reasoning a provider does not expose, and a model that
        reaches the same conclusion without narrating it is invisible here. It
        is an additional place to catch the failure, not a guarantee of catching
        it — which is why nothing above this line depends on it.
        """
        agent, identity, _ = self.resolve(agent_slug, credential)
        return self.evaluate(
            agent=agent,
            identity=identity,
            content=content,
            surface="reasoning",
            intent=intent,
            taint_source=taint_source,
            trace=trace,
            persist=persist,
        )

    def guard_file(
        self,
        *,
        agent_slug: str,
        filename: str,
        data: bytes,
        trace: Trace | None = None,
        credential: str | None = None,
        persist: bool = True,
    ) -> EnforcementResult:
        """Check a file an agent is about to read, layer by layer (a4).

        A document is not a string. It has a body a person proofreads and
        parts nobody opens — document properties, review comments, alt text,
        an SVG `<title>` — and the model reads all of them. The attack is
        old and specific: a resume whose white-on-white text tells the
        screening agent to rank the candidate first.

        So the file is split by `guardrails.files.normalise` and the hidden
        layers are checked **separately from the visible ones**, with the
        hidden result taking precedence. The same sentence in the body is a
        sentence somebody wrote; in `docProps` it is a sentence nobody was
        meant to read, and treating those alike throws away the only signal
        that distinguishes a document from an attack.

        A layer that could not be read is recorded on the result as a
        degradation rather than dropped. An image needs OCR and a PDF needs a
        parser; when either is missing the answer is "this was not checked",
        which the caller can act on. Returning no findings for a file nobody
        looked inside is the failure this product exists to argue against.
        """
        from agentfox.detection.files import normalise

        scan = normalise(filename, data)
        agent, identity, _ = self.resolve(agent_slug, credential)

        # Hidden first: if anything is going to decide the verdict it should
        # be the layer with the stronger claim, and `evaluate` persists a
        # decision per call.
        ordered = [(True, scan.hidden_text), (False, scan.visible_text)]
        result: EnforcementResult | None = None
        for is_hidden, text in ordered:
            if not text.strip():
                continue
            outcome = self.evaluate(
                agent=agent,
                identity=identity,
                content=text,
                surface="retrieved",
                taint_source="tool_result",
                trace=trace,
                persist=persist,
            )
            if is_hidden and outcome.detections_found:
                outcome.reason = (
                    f"{outcome.reason} — found in a part of '{filename}' a reader would not see"
                ).strip(" —")
            if result is None or _VERDICT_RANK.get(
                outcome.effective_verdict, 0
            ) > _VERDICT_RANK.get(result.effective_verdict, 0):
                result = outcome

        if result is None:
            result = EnforcementResult(verdict="allow", effective_verdict="allow")

        for gap in scan.unread:
            # Surfaced the way a timed-out detector is: the gap is part of the
            # decision record, not a silence.
            result.degraded.append(f"file.unread:{gap['part']}")
            result.explanation.setdefault("unread_layers", []).append(gap)
        result.explanation["file"] = scan.to_json()
        return result

    def guard_agent_message(
        self,
        *,
        sender_slug: str,
        content: str,
        recipient_slug: str | None = None,
        nonce: str | None = None,
        timestamp: float | None = None,
        signature: str | None = None,
        trace: Trace | None = None,
        persist: bool = True,
    ) -> EnforcementResult:
        """Authorise a sub-agent's message to another agent, as another agent's
        untrusted claim rather than as a tool's return value.

        Three checks layer on top of the generic detector pipeline, each mapped
        to the corresponding half of OWASP ASI07:

        * **Agent-card check** — the declared sender must resolve to a
          registered agent, reusing :func:`registry.service.attest_registry`'s
          declared-vs-observed comparison rather than a second attestation
          mechanism. An unregistered sender cannot be vouched for.
        * **Replay protection** — ``(sender, nonce)`` must be unique. A repeat
          fails to insert into ``agent_message_log`` and the message is blocked
          as a replay, full stop, before the detector pipeline even runs.
        * **Signature verification** — where the sender has a registered signing
          key (:mod:`agent_messaging`), the HMAC is checked. Where the transport
          is external (a customer's own A2A/MCP bus) and no signature is
          present, the message is reported **unsigned** rather than silently
          trusted — the same "declare the gap, don't hide it" convention used
          elsewhere for what a check doesn't cover.
        """
        agent, identity, _ = self.resolve(sender_slug, None)
        agent_card_match = agent is not None and bool(agent.registered)
        # Replay protection is `(sender, nonce)` uniqueness, so it only exists
        # when the sender sends a nonce. Storing a missing nonce as "" would make a
        # sender's second nonce-less message collide with its first and be blocked as
        # a replay. Without a nonce there is nothing to protect with:
        # the replay check is skipped and the gap is declared on the decision
        # (`agent_message.no_nonce`, `replay_protected: false`) — the same "declare
        # the gap, don't hide it" treatment an unsigned message gets. Requiring a
        # nonce would refuse every legitimate sender that does not send one; senders
        # that need replay protection send a nonce (and sign it).
        replay_protected = bool(nonce)
        signed_nonce = nonce or ""
        # The log row still needs a unique key; a random one can never collide.
        stored_nonce = nonce or f"none:{uuid.uuid4().hex}"

        replayed = False
        if persist:
            # A SAVEPOINT, not the whole transaction: a plain `session.rollback()`
            # on the IntegrityError would discard *everything* pending on this
            # session, not just this one failed insert — including, in the
            # request path, the trace/span rows already added ahead of this call.
            try:
                with self.session.begin_nested():
                    self.session.add(
                        AgentMessageLog(
                            sender_slug=sender_slug,
                            recipient_slug=recipient_slug,
                            nonce=stored_nonce,
                            signed=signature is not None,
                            agent_card_match=agent_card_match,
                            trace_id=trace.id if trace else None,
                        )
                    )
                    self.session.flush()
            except IntegrityError:
                replayed = True

        signature_valid: bool | None = None
        if signature is not None and agent is not None and not replayed:
            key_row = self.session.scalar(
                select(AgentSigningKey).where(
                    AgentSigningKey.agent_id == agent.id,
                    AgentSigningKey.revoked_at.is_(None),
                )
            )
            if key_row is None:
                signature_valid = False
            else:
                try:
                    raw_key = decrypt_secret(key_row.key_encrypted)
                    signature_valid = verify_message(
                        raw_key,
                        sender=sender_slug,
                        nonce=signed_nonce,
                        payload=content,
                        timestamp=timestamp or 0.0,
                        signature=signature,
                        validity_seconds=self.settings.agent_message_validity_seconds,
                    )
                except DecryptionFailed:
                    signature_valid = False

        # These are decided *before* `evaluate`, and handed to it, so the Decision
        # row and the audit chain record the verdict the caller gets. Applied to the
        # result afterwards, a blocked replay would sit in the audit chain as
        # `decision.allow`.
        forced: list[dict[str, Any]] = []
        extra_taint: dict[str, Any] = {"replay_protected": replay_protected}
        replay_reason = f"replayed message: (sender='{sender_slug}', nonce) was already seen"
        if replayed:
            forced.append(
                _fired_rule("agent_message.replay", "block", replay_reason, controls=["NOM-IAM-08"])
            )
        elif not agent_card_match:
            forced.append(
                _fired_rule(
                    "agent_message.agent_card_mismatch",
                    "escalate",
                    f"sender '{sender_slug}' is not a registered agent — "
                    "its agent-card cannot be verified",
                    controls=["NOM-IAM-08"],
                )
            )
        elif signature_valid is False:
            forced.append(
                _fired_rule(
                    "agent_message.bad_signature",
                    "block",
                    "signature did not verify against the sender's registered signing key",
                    controls=["NOM-IAM-08"],
                )
            )
        elif signature is None:
            extra_taint["unsigned"] = True
            forced.append(
                _fired_rule(
                    "agent_message.unsigned",
                    "observe",
                    "message arrived unsigned — either the transport is not "
                    "AgentFox's own, or the sender has no registered signing key",
                    controls=["NOM-IAM-08"],
                )
            )
        if not replay_protected:
            forced.append(
                _fired_rule(
                    "agent_message.no_nonce",
                    "observe",
                    "message carried no nonce, so replay protection was not applied — "
                    "send a unique nonce per message to have repeats refused",
                    controls=["NOM-IAM-08"],
                )
            )

        result = self.evaluate(
            agent=agent,
            identity=identity,
            content=content,
            surface="agent_message",
            trace=trace,
            taint_source="subagent",
            persist=persist,
            forced_rules=forced,
            extra_taint=extra_taint,
        )
        if replayed:
            result.reason = replay_reason

        if persist:
            log_row = self.session.scalar(
                select(AgentMessageLog)
                .where(
                    AgentMessageLog.sender_slug == sender_slug,
                    AgentMessageLog.nonce == stored_nonce,
                )
                .order_by(AgentMessageLog.created_at.desc())
            )
            if log_row is not None:
                log_row.signature_valid = signature_valid
                log_row.decision_id = result.decision_id

        return result
