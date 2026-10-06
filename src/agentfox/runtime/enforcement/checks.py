"""The content checks `evaluate()` runs beside the detector pipeline: evidence,
disclosure, control flow, sycophancy, commitments, trajectory and context integrity.
"""

from __future__ import annotations

import logging
from typing import Any

from agentfox.containment.control_flow import Plan
from agentfox.containment.control_flow import check_selection as check_tool_selection
from agentfox.core.models import Agent
from agentfox.detection import DetectionContext
from agentfox.detection.trajectory import ENTITY as TRAJECTORY_ENTITY
from agentfox.detection.trajectory import SCAN_CHARS as TRAJECTORY_SCAN_CHARS
from agentfox.detection.trajectory import assess as assess_trajectory
from agentfox.grounding.commitments import (
    adverse_action_risk,
    check_disclosure,
    claims_human,
    detect_commitments,
)
from agentfox.grounding.context_integrity import (
    chunk_quality,
    document_quality,
    memory_binding_breach,
    retrieval_drift,
)
from agentfox.grounding.context_integrity import worst as worst_context_verdict
from agentfox.grounding.entitlement import (
    aggregation_risk,
    filter_retrieval,
    inference_risk,
    record_disclosure,
)
from agentfox.grounding.integrity import assess_integrity
from agentfox.grounding.provenance import assess_provenance
from agentfox.grounding.register import check_register
from agentfox.grounding.sycophancy import check_premises

log = logging.getLogger("agentfox.runtime.enforcement")


#: The commitment and context-integrity post-flight checks are linear in the content
#: they read, and every one of them is a regex or character scan rather than a model
#: call. Measured on this machine: together they cost ~0.7ms on a 1.6KB answer, ~35ms on
#: an 81KB one and ~170ms on 405KB — the last of which would eat most of the 300ms
#: enforcement budget on a single oversized retrieved payload. Capping the scanned
#: prefix bounds the work at ~13ms. A promise or a corruption that appears only after
#: 32KB of text is a case this check honestly does not cover, which is a better failure
#: than a blown budget on the request path.
_SCAN_CHARS = 32_000


_SCAN_CHUNKS = 50


_SCAN_CHUNK_CHARS = 2_000


#: `document_quality` codes meaning the *bytes* are damaged, as opposed to its
#: prose-shape heuristics (`low-text-density`, `lost-word-boundaries`,
#: `hyphenated-line-breaks`). A serialised tool result legitimately trips the shape
#: heuristics — measured: an ordinary 2.2KB JSON payload and a 1.2KB CSV both report
#: `low-text-density` — so only these apply on `tool_result`, where the content is a
#: structure rather than a document. On `retrieved`, where the content really is
#: prose from a corpus, the shape heuristics are the point and all of them run.
_CORRUPTION_CODES = frozenset(
    {"mojibake", "unknown-characters", "control-characters", "empty-extraction"}
)


#: context_integrity's three-value scale onto the `Finding` severity vocabulary.
#: Never `critical`: see `_commitment_checks` on why nothing here self-escalates.
_CONTEXT_SEVERITY = {"warn": "low", "degraded": "medium", "reject": "high"}


class _ChecksMixin:
    """Enforcer's content checks. Mixed into :class:`Enforcer`, never used alone."""

    def _evidence_checks(
        self, agent: Agent | None, surface: str, content: str, intent: str | None
    ) -> dict[str, Any]:
        """Source authority and numeric integrity, on the output surface.

        Both need the evidence the answer was built from, which the caller supplies
        via ``self.evidence``. When nothing is supplied they return quietly rather
        than guessing: an integrity check that invents its own ground truth is worse
        than none.
        """
        if surface != "output" or not content:
            return {}
        evidence = self.evidence or {}
        chunks = evidence.get("chunks")
        records = evidence.get("records")
        entities = evidence.get("entities")
        if not any((chunks, records, entities, evidence.get("components"))):
            return {}

        context_text = " ".join(str(c.get("text") or "") for c in (chunks or []))
        provenance = assess_provenance(
            self.session, content, chunks, agent_domain=evidence.get("domain")
        )
        integrity = assess_integrity(
            question=intent or evidence.get("question", ""),
            answer=content,
            context=context_text,
            records=records,
            entities=entities,
            components=evidence.get("components"),
        )

        issues: list[dict[str, Any]] = []
        for breach in provenance.breaches:
            issues.append(
                {
                    "type": "source_authority",
                    "severity": "high" if breach["kind"] == "deprecated_source" else "medium",
                    "title": breach["reason"],
                    **breach,
                }
            )
        for fabricated in provenance.fabricated:
            issues.append(
                {
                    "type": "fabricated_citation",
                    "severity": "high",
                    "title": fabricated["reason"],
                    **fabricated,
                }
            )
        for conflict in provenance.conflicts:
            issues.append(
                {
                    "type": "source_conflict",
                    "severity": "medium",
                    "title": conflict["reason"],
                    **conflict,
                }
            )
        for issue in integrity.issues:
            issues.append(
                {
                    "type": "integrity_error",
                    "severity": "high"
                    if issue["kind"] in ("hallucinated_record", "entity_confusion")
                    else "medium",
                    "title": issue["reason"],
                    **issue,
                }
            )
        return {
            "provenance": provenance.to_json(),
            "integrity": integrity.to_json(),
            "evidence_issues": issues,
        }

    def _disclosure_checks(
        self, agent: Agent | None, surface: str, content: str, trace_id: str | None
    ) -> dict[str, Any]:
        """What this human may see, and what the answer disclosed anyway.

        The pre-filter belongs to whoever performs retrieval, so it is exposed
        separately; this is the post-flight half, which catches the two disclosures no
        access check can — an aggregate over too few people, and an attribute the model
        inferred rather than retrieved.
        """
        if surface != "output" or not content:
            return {}
        evidence = self.evidence or {}
        principal = evidence.get("principal")
        chunks = evidence.get("chunks") or []
        issues: list[dict[str, Any]] = []
        out: dict[str, Any] = {}

        if principal is not None:
            decision = filter_retrieval(
                self.session,
                principal,
                chunks,
                purpose=evidence.get("purpose"),
            )
            record_disclosure(
                self.session,
                decision,
                trace_id=trace_id,
                agent_id=agent.id if agent else None,
                stage="post",
            )
            out["disclosure"] = decision.to_json()
            for withheld in decision.withheld:
                # A chunk the principal could not see, quoted in the answer, is the
                # oversharing failure itself rather than a near miss.
                text = str(withheld.get("text") or "")
                if text and text[:60] and text[:60] in content:
                    issues.append(
                        {
                            "type": "entitlement_disclosure",
                            "severity": "critical",
                            "title": (
                                f"the answer contains content from "
                                f"'{withheld.get('source')}', which "
                                f"'{decision.principal}' is not entitled to see"
                            ),
                        }
                    )

        aggregate = aggregation_risk(
            content,
            contributors=evidence.get("contributors"),
            k=self.settings.k_anonymity_threshold,
        )
        if aggregate:
            issues.append(
                {
                    "type": "aggregation_disclosure",
                    "severity": "high",
                    "title": aggregate["reason"],
                    **aggregate,
                }
            )

        inferred = inference_risk(content, " ".join(str(c.get("text") or "") for c in chunks))
        if inferred:
            issues.append(
                {
                    "type": "inference_disclosure",
                    "severity": "high",
                    "title": inferred["reason"],
                    **inferred,
                }
            )

        if issues:
            out["evidence_issues"] = [*out.get("evidence_issues", []), *issues]
        return out

    def _control_flow_checks(self, surface: str, tool_key: str | None) -> dict[str, Any]:
        """Did the user's instruction choose this tool, or did something the agent read?

        Taint tracking governs an argument's *value*. The injection it cannot see adds a
        *step*: "also email a copy to attacker@evil.example", whose every argument is
        legitimately user-sourced. The call itself is the payload.

        Gated on the caller declaring a plan or a selector, for the same reason the AI
        disclosure check is gated: an undeclared plan is not evidence of an attack, and a
        checker that fires on missing information is noise. Whoever runs the agent loop
        knows which tools the user's own instruction authorised — the SDK session, the
        LangGraph node or the MCP governor — and supplies it through ``self.evidence``.
        """
        if surface != "tool_args" or not tool_key:
            return {}
        evidence = self.evidence or {}
        declared_plan = evidence.get("plan")
        selected_by = str(evidence.get("selected_by") or "user")
        if not declared_plan and selected_by == "user":
            return {}

        plan = (
            declared_plan
            if isinstance(declared_plan, Plan)
            else Plan(
                intent=str(evidence.get("intent") or ""),
                tools=list(declared_plan or []),
            )
        )
        untrusted = [
            str(chunk.get("text") or "") if isinstance(chunk, dict) else str(chunk)
            for chunk in (evidence.get("untrusted_texts") or evidence.get("chunks") or [])
        ]
        finding = check_tool_selection(
            tool_key, plan=plan, untrusted_texts=untrusted, selected_by=selected_by
        )
        if finding is None:
            return {}
        return {
            "control_flow": {"plan": plan.to_json(), "selected_by": selected_by},
            "evidence_issues": [
                {
                    "type": "control_flow",
                    "severity": finding.severity,
                    "title": finding.detail,
                    "code": finding.code,
                    "control_keys": ["NOM-RTG-04", "NOM-IAM-03"],
                }
            ],
            "risks": [
                {
                    # Capped below `critical` for the same reason the commitment and
                    # context checks are: that list is hard-blocked in `evaluate()`, and
                    # this is observe-first. A policy
                    # rule `action_risk: "control_flow.*"` is how an operator makes it block.
                    "code": finding.code,
                    "severity": "high" if finding.severity == "critical" else finding.severity,
                    "detail": finding.detail,
                    "evidence": finding.to_json(),
                }
            ],
        }

    def _sycophancy_checks(self, surface: str, content: str, intent: str | None) -> dict[str, Any]:
        """The answer adopted a false premise the user asserted.

        Checked against the caller's grounded record, never against the model's opinion of
        it: `evidence["grounded"]` maps a subject to its real value. Without that there is
        no authority to contradict anyone with, so nothing fires — which is also what keeps
        opinions and genuinely ungrounded matters out of it.
        """
        if surface != "output" or not content:
            return {}
        evidence = self.evidence or {}
        grounded = evidence.get("grounded")
        question = str(evidence.get("question") or intent or "")
        if not grounded or not question:
            return {}

        findings = check_premises(question, content, grounded)
        if not findings:
            return {}
        return {
            "evidence_issues": [
                {
                    "type": "sycophancy",
                    "severity": finding.severity,
                    "title": finding.detail,
                    "code": finding.code,
                    "control_keys": ["NOM-RTG-12"],
                }
                for finding in findings
            ],
            "risks": [
                {
                    "code": finding.code,
                    "severity": "high" if finding.severity == "critical" else finding.severity,
                    "detail": finding.detail,
                    "evidence": finding.to_json(),
                }
                for finding in findings
            ],
        }

    def _commitment_checks(
        self, agent: Agent | None, surface: str, content: str, intent: str | None
    ) -> dict[str, Any]:
        """The obligations an answer created, on the output surface.

        Built to the shape `_evidence_checks` established: findings are recorded and
        surfaced, and nothing here decides a verdict by itself.

        Two of the four detectors run unconditionally, because they are quiet on
        ordinary traffic rather than because running them is free — `detect_commitments`
        keys on performative verbs ("I guarantee", "your refund has been approved") and
        `check_register` fires only in a regulated domain or on an unhedged claim about
        the future. The other two are gated on the caller declaring the fact they need,
        because inferring it would mean inventing ground truth:

        * **AI disclosure** (EU AI Act Art. 50) resolves to *breach* for any
          message on a human-facing channel that does not identify itself as automated.
          That is correct as an obligation and wrong as a default — inferred, it would
          report a breach on essentially every response this product has governed. The
          obligation exists only where there is a human counterparty, and no property of
          the text establishes that, so the caller supplies `evidence["channel"]` /
          `["counterparty"]`.
        * **Adverse action** (ECOA/FCRA) is checked against the *decision record*
          rather than the prose, precisely because a message can read as an explanation
          while the record behind it is empty. No record supplied, no check performed.

        `fairness_probe` is deliberately NOT wired here, and should not be. It is
        an aggregate statistic — selection rates by group against the four-fifths rule,
        with a 30-observation floor below which it refuses to report at all — computed
        over a population of decisions. One request cannot exhibit disparate impact, and
        calling it per-request could only ever return the `underpowered` result while
        implying the check had run. It belongs to the compliance/eval path, over a
        decision population, and stays there.
        """
        if surface != "output" or not content:
            return {}
        evidence = self.evidence or {}
        text = content[:_SCAN_CHARS]
        issues: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        out: dict[str, Any] = {}

        # A commitment is made in the speech act, so this reads the answer and
        # nothing else. `authorised` is the caller's statement that the agent genuinely
        # held the authority; the commitment is still recorded, it simply is not a
        # finding, which is the module's own documented behaviour.
        authorised = bool(evidence.get("authorised"))
        commitments = detect_commitments(text, authorised=authorised)
        # The closed set reaches 26.7% recall at 100% precision on the refund
        # corpus. The rest commit without a binding word — presupposition, a
        # double negative, an oblique "that's sorted", or Spanish — which a
        # regex cannot express. An enabled judgment tier adds those; it never
        # drops a deterministic finding, and no-ops when no tier is enabled.
        from agentfox.capabilities.judgment.commitments import augment as _judge_commitments

        commitments = _judge_commitments(commitments, text, authorised=authorised)
        if commitments:
            out["commitments"] = [c.to_json() for c in commitments]
            for commitment in commitments:
                issues.append(
                    {
                        "type": "binding_commitment",
                        "severity": "high",
                        "title": f"the answer {commitment.why}: {commitment.text!r}",
                        "kind": commitment.kind,
                        "control_keys": ["NOM-RTG-11"],
                    }
                )
                risks.append(
                    {
                        "code": f"commitment.{commitment.kind}",
                        "severity": "high",
                        "detail": f"{commitment.why}: {commitment.text!r}",
                        "evidence": commitment.to_json(),
                    }
                )

        # Specificity licensed by epistemic standing. `licensed_domains` is the
        # declaration that makes this workable: an operator that employs clinicians
        # licenses `medical` and the instruction findings stop firing. Standing is
        # declared, never inferred.
        register = check_register(
            text,
            request=intent or str(evidence.get("question") or ""),
            licensed_domains=tuple(evidence.get("licensed_domains") or ()),
        )
        if register.findings:
            out["register"] = register.to_json()
            for finding in register.findings:
                issues.append(
                    {
                        "type": "register_breach",
                        "severity": finding.severity,
                        "title": finding.detail,
                        "code": finding.code,
                        "domain": register.domain,
                        "control_keys": ["NOM-RTG-11"],
                    }
                )
                risks.append(
                    {
                        "code": f"register.{finding.code}",
                        # Capped below `critical` on purpose — a critical entry in
                        # `action["risks"]` is hard-blocked by the action-assurance
                        # branch in `evaluate()`, and commitments are observe-first. The
                        # severity the detector actually assigned is preserved on the finding.
                        "severity": "high" if finding.severity == "critical" else finding.severity,
                        "detail": finding.detail,
                        "evidence": finding.to_json(),
                    }
                )

        # An answer that says it is a person. Ungated, unlike the disclosure
        # duty below: a false claim to be human is wrong whoever is listening. This is
        # what `eu.art50.impersonation` reads (via `action_risk`).
        human_claim = claims_human(text)
        if human_claim:
            out["claims_human"] = human_claim
            issues.append(
                {
                    "type": "ai_impersonation",
                    "severity": "high",
                    "title": f"the answer claims to be a person: {human_claim!r}",
                    "control_keys": ["NOM-GOV-05"],
                }
            )
            risks.append(
                {
                    "code": "disclosure.claims_human",
                    "severity": "high",
                    "detail": f"the answer claims to be a person: {human_claim!r}",
                    "evidence": {"match": human_claim},
                }
            )

        # See the docstring: gated on a declared counterparty, never inferred.
        if evidence.get("channel") or evidence.get("counterparty"):
            disclosure = check_disclosure(
                text,
                channel=str(evidence.get("channel") or "chat"),
                counterparty=str(evidence.get("counterparty") or "human"),
                already_disclosed=bool(evidence.get("already_disclosed")),
                exempt=bool(evidence.get("disclosure_exempt")),
            )
            # `ai_disclosure`, not `disclosure`: `_disclosure_checks` already owns that
            # key for the entitlement decision, and the two answer different
            # questions — what this person may see, versus whether they were told they
            # were talking to a machine.
            out["ai_disclosure"] = disclosure.to_json()
            if disclosure.breach:
                issues.append(
                    {
                        "type": "ai_disclosure_missing",
                        "severity": "medium",
                        "title": (
                            "the person was not told they were talking to an AI system: "
                            f"{disclosure.reason}"
                        ),
                        "control_keys": ["NOM-GOV-05"],
                    }
                )
                risks.append(
                    {
                        "code": "disclosure.ai_missing",
                        "severity": "medium",
                        "detail": disclosure.reason,
                        "evidence": disclosure.to_json(),
                    }
                )

        # Checked against the recorded decision, which is what has to stand up.
        record = evidence.get("decision") or {}
        outcome = str(record.get("outcome") or "")
        if outcome:
            adverse = adverse_action_risk(
                outcome,
                reasons=[str(r) for r in (record.get("reasons") or [])],
                domain=str(record.get("domain") or evidence.get("domain") or ""),
                text=text,
            )
            out["adverse_action"] = adverse.to_json()
            for detail in adverse.findings:
                issues.append(
                    {
                        "type": "adverse_action",
                        "severity": "high" if adverse.statutory else "medium",
                        "title": detail,
                        "outcome": adverse.outcome,
                        "domain": adverse.domain,
                        "statutory": adverse.statutory,
                        "control_keys": ["NOM-RTG-11"],
                    }
                )
                risks.append(
                    {
                        "code": "adverse_action.statutory"
                        if adverse.statutory
                        else "adverse_action.unexplained",
                        "severity": "high" if adverse.statutory else "medium",
                        "detail": detail,
                        "evidence": adverse.to_json(),
                    }
                )

        if issues:
            out["evidence_issues"] = issues
        if risks:
            out["risks"] = risks
        return out

    def _trajectory_checks(self, surface: str, window: list[str] | None) -> dict[str, Any]:
        """Whether the *conversation* is escalating, not whether this turn is.

        Built to the shape `_commitment_checks` established, for the same reason: the
        finding is recorded and surfaced on the `action["risks"]` channel, and nothing
        here decides a verdict. See `trajectory.py` for the measurement.

        Why this is the integration point. The trajectory score hangs off the per-turn
        recording hook, because a check with a natural per-turn hook to attach to gets
        called on live traffic. `check_conversation_window` is that hook on this path:
        it already runs once per user turn, already holds a `session_id` and the
        recorded history behind it, and is already called from `autoguard._govern`'s
        pre-flight and the gateway playground route. Nothing else needed wiring, which
        is the whole point — `docs/design/failure-modes.md` exists to catch modules that
        are built and never called, and a trajectory scorer reachable only from its own
        tests would be exactly that.

        **Sub-threshold detector activations.** The trajectory score's first component
        is a detector finding above zero and below the blocking threshold. The
        per-message run for the *current* turn already exists, but the equivalent number
        for the earlier turns in the window is not persisted anywhere —
        `ConversationTurn.signals_json` is written by `escalation.record_turn` and
        carries escalation's signals, not detector scores. So each turn in the window is
        scored here, through the real pipeline, at a measured ~0.4ms per turn. Worth
        knowing what that buys: `benchmarks/crescendo/` measures the shipped detectors
        returning **exactly zero on all 132 turns** of that corpus, so on crescendo
        traffic this component contributes nothing and the drift and reframing
        components are doing all the work. It is kept because it is cheap and because a
        conversation that mixes gradual escalation with clumsier probing is the case
        where it pays.
        """
        if surface != "input" or not window or len(window) < 3:
            return {}

        # Never let a governance extra break a request, and never let it eat the
        # budget: the per-turn scoring is bounded by the window size (<= 8 short
        # strings) and skipped wholesale if anything goes wrong.
        try:
            detector_scores = self._window_detector_scores(window)
            assessment = assess_trajectory(window, detector_scores=detector_scores)
        except Exception as exc:  # pragma: no cover - defence in depth
            log.debug("agentfox: trajectory scoring skipped: %s", exc)
            return {}

        out: dict[str, Any] = {"trajectory": assessment.to_json()}
        if not assessment.fired:
            return out
        out["evidence_issues"] = [
            {
                "type": "trajectory_drift",
                # High, never critical: a `critical` entry in `action["risks"]` is
                # hard-blocked by the action-assurance branch in `evaluate()`, and
                # trajectory is observe-first. Same cap, same reason, as the commitment
                # findings.
                "severity": "high",
                "title": f"{TRAJECTORY_ENTITY}: {assessment.reason}",
                "entity": TRAJECTORY_ENTITY,
                "control_keys": ["NOM-RTG-06"],
            }
        ]
        out["risks"] = [
            {
                "code": assessment.code,
                "severity": "high",
                "detail": assessment.reason,
                "evidence": assessment.to_json(),
            }
        ]
        return out

    def _window_detector_scores(self, window: list[str]) -> list[float]:
        """Each window turn's per-message detector max score (the trajectory's first component).

        Runs the same pipeline the per-message path runs, one short turn at a time.
        A degraded or erroring run contributes 0.0 rather than failing the check —
        the component is additive, so a missing one under-reports rather than
        inventing a trajectory.

        Capped at `trajectory.SCAN_CHARS` per turn, and that cap is load-bearing
        rather than tidy: this runs the pipeline once *per turn in the window*,
        so an uncapped 250KB turn costs about 2.5 seconds against a 300ms budget.
        The per-message path still sees the whole message; what is bounded here is
        only the proxy feeding the trajectory score.
        """
        context = DetectionContext(surface="input", taint_source="user")
        scores: list[float] = []
        for text in window:
            try:
                scores.append(self.pipeline.run(text[:TRAJECTORY_SCAN_CHARS], context).max_score)
            except Exception:  # pragma: no cover - defence in depth
                scores.append(0.0)
        return scores

    def _context_checks(
        self, surface: str, content: str, memory_entry: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Whether the context was intact, on the surfaces context arrives on.

        The failure this addresses is invisible from the far end of the pipe: a model
        handed a mangled context does not report a mangled context, it answers fluently
        from whatever survived. Groundedness then confirms the answer matches that
        context and nothing anywhere reports a problem. So these run on the way *in* —
        `retrieved` and `tool_result` for content quality, `memory_write` for binding —
        and, unlike the opt-in `POST /provenance/context-check` route, on ordinary
        traffic without the caller asking.

        `assemble_context` is not called here, on purpose. It is the one function in the
        module that also *repairs* (it reorders for salience), and it needs the ranked
        chunk list and the real token budget, both of which belong to whoever performed
        the retrieval. Manufacturing an assembly step inside `evaluate()` would measure a
        fit this code had just invented. It is exposed as `Enforcer.assemble_context` for
        that caller instead.
        """
        if not content and not memory_entry:
            return {}
        evidence = self.evidence or {}
        findings: list[Any] = []
        out: dict[str, Any] = {}

        if surface in ("retrieved", "tool_result") and content:
            quality = document_quality(
                content[:_SCAN_CHARS], source_key=str(evidence.get("source") or "")
            )
            document_findings = [
                f
                for f in quality.findings
                if surface != "tool_result" or f.code in _CORRUPTION_CODES
            ]
            findings.extend(document_findings)
            if document_findings:
                out["document_quality"] = {
                    "score": round(quality.score, 3),
                    "usable": quality.usable,
                    "findings": [f.to_json() for f in document_findings],
                }

            # Chunk coherence needs the chunk boundaries, which only the retriever has —
            # the assembled string on this surface has already lost them. Supplied via
            # the same `evidence["chunks"]` the evidence checks read, so a caller that has
            # wired evidence once gets this for free.
            if chunks := evidence.get("chunks"):
                findings.extend(
                    chunk_quality(
                        [
                            {"text": str(c.get("text") or "")[:_SCAN_CHUNK_CHARS]}
                            if isinstance(c, dict)
                            else str(c)[:_SCAN_CHUNK_CHARS]
                            for c in list(chunks)[:_SCAN_CHUNKS]
                        ]
                    )
                )

            # Regression is only visible against a baseline, so this needs one
            # rather than a threshold. Both come from the caller or it does not run.
            current, baseline = evidence.get("retrieval"), evidence.get("baseline")
            if current and baseline and (drift := retrieval_drift(current, baseline)):
                findings.append(drift)

        elif surface == "memory_write":
            # The boundary that matters within one tenant is the *subject* the
            # memory is about, not the tenant that owns the store. Needs a principal to
            # check against; without one there is nothing to compare and it stays quiet.
            principal = evidence.get("principal")
            entries = [dict(e) for e in (evidence.get("memory") or []) if isinstance(e, dict)]
            if memory_entry is not None:
                entries.append(memory_entry)
            if principal and entries:
                findings.extend(
                    memory_binding_breach(
                        entries,
                        principal=str(principal),
                        session_id=evidence.get("session_id"),
                    )
                )

        if not findings:
            return out

        out["context"] = {
            "verdict": worst_context_verdict(findings),
            "findings": [f.to_json() for f in findings],
        }
        # Recorded, and left to policy. `verdict` above is what the *module* would say
        # in isolation (`degraded` maps to abstain, `reject` to block); it is reported
        # rather than applied, because dropping a corrupt document is a decision with a
        # cost that belongs to the operator.
        out["evidence_issues"] = [
            {
                "type": "context_integrity",
                "severity": _CONTEXT_SEVERITY.get(f.severity, "medium"),
                "title": f.detail,
                "code": f.code,
                "surface": surface,
                "control_keys": ["NOM-RTG-13" if surface == "memory_write" else "NOM-RTG-12"],
            }
            for f in findings
        ]
        out["risks"] = [
            {
                "code": f"context.{f.code}",
                "severity": _CONTEXT_SEVERITY.get(f.severity, "medium"),
                "detail": f.detail,
                "evidence": f.to_json(),
            }
            for f in findings
        ]
        return out
