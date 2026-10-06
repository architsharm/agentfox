"""Auditor-ready evidence packages (P5-3, P5-7, NOM-AUD-03).

The test a package has to pass: an auditor who has never heard of us, given only
the zip file, can (a) see what was in scope, (b) read what the agent actually did,
(c) see which policy version was in force at the time, and (d) **independently
verify that the record was not altered** — without trusting us or calling our API.

That is why ``verify_chain.py`` ships *inside* the package: a standalone script with
no imports beyond the standard library that re-derives the hash chain from the
exported rows.

Draft framework mappings ship inside the package too (Appendix B §B.6), but each
one carries an explicit ``DRAFT — UNVERIFIED / NOT LEGAL ADVICE`` chip rather than
being silently dropped. Hiding an unreviewed mapping told an auditor nothing was
outstanding; badging it tells them exactly what still needs review.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox import __version__
from agentfox.core.config import get_settings
from agentfox.core.models import (
    Agent,
    ApprovalRequest,
    AuditCheckpoint,
    AuditEntry,
    ControlStatus,
    Decision,
    EvalRun,
    EvidencePackage,
    Finding,
    FrameworkMapping,
    PolicyVersion,
    RiskAssessment,
    Trace,
    utcnow,
)
from agentfox.prove.audit import chain
from agentfox.prove.audit.trace import full_trace

VERIFIER_SCRIPT = '''#!/usr/bin/env python3
"""Standalone verifier for an AgentFox evidence package.

Stdlib only. Run from inside the extracted package:

    python3 verify_chain.py

Re-derives every entry digest and the chain linkage from audit_entries.json and
checks the signed checkpoints if a key is supplied via AGENTFOX_AUDIT_KEY
(NOMETRIA_AUDIT_KEY is still read, for packages verified with the old name).
Exit code 0 = intact, 1 = tampered.
"""
import hashlib, hmac, json, os, sys

GENESIS = "0" * 64

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)

def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def main():
    entries = sorted(json.load(open("audit_entries.json")), key=lambda r: r["seq"])
    try:
        checkpoints = json.load(open("audit_checkpoints.json"))
    except FileNotFoundError:
        checkpoints = []
    if not entries:
        print("no entries to verify")
        return 0

    breaks, prev = [], GENESIS if entries[0]["seq"] == 1 else None
    expected = entries[0]["seq"]
    for row in entries:
        seq = row["seq"]
        if seq != expected:
            breaks.append(
                (seq, "gap", "expected seq %d, found %d - deleted" % (expected, seq))
            )
            expected = seq
        expected += 1
        # A scoped package withholds the payload of entries about other agents; the
        # entry digest below still covers its payload digest, so linkage is checked.
        # A withheld row must really carry no payload, or the flag would hide an edit.
        if row.get("payload_withheld") and row.get("payload") is None:
            pass
        elif sha256(canonical(row.get("payload") or {})) != row["payload_digest"]:
            breaks.append((seq, "payload_mismatch", "payload does not match its digest"))
        recomputed = sha256("%s|%s|%s|%s|%s" % (
            seq, row["occurred_at"], row["action"], row["payload_digest"], row["prev_digest"]))
        if recomputed != row["digest"]:
            breaks.append((seq, "digest_mismatch", "entry digest does not match its contents"))
        if prev is not None and row["prev_digest"] != prev:
            breaks.append((seq, "prev_mismatch", "broken linkage - insertion or reordering"))
        prev = row["digest"]

    # AGENTFOX_ first, the pre-rename NOMETRIA_ name second; and the operator's own
    # signing-key variable as a last resort, since that is the one already set.
    key = next(
        (
            os.environ[name]
            for name in (
                "AGENTFOX_AUDIT_KEY",
                "NOMETRIA_AUDIT_KEY",
                "AGENTFOX_AUDIT_SIGNING_KEY",
                "NOMETRIA_AUDIT_SIGNING_KEY",
            )
            if os.environ.get(name)
        ),
        None,
    )
    if key:
        by_seq = {r["seq"]: r for r in entries}
        for cp in checkpoints:
            sig = hmac.new(key.encode(), cp["digest"].encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, cp.get("signature", "")):
                breaks.append((cp["seq"], "checkpoint_signature", "checkpoint signature mismatch"))
            elif cp["seq"] in by_seq and by_seq[cp["seq"]]["digest"] != cp["digest"]:
                breaks.append(
                    (cp["seq"], "checkpoint_digest", "history rewritten under a checkpoint")
                )
    else:
        print("note: AGENTFOX_AUDIT_KEY not set - checkpoint signatures not verified")

    print("entries checked: %d (seq %d..%d)"
          % (len(entries), entries[0]["seq"], entries[-1]["seq"]))
    if breaks:
        print("CHAIN INVALID - %d break(s):" % len(breaks))
        for seq, kind, detail in breaks:
            print("  seq %s  %s: %s" % (seq, kind, detail))
        return 1
    print("CHAIN INTACT")
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.isoformat()


def build(
    session: Session,
    *,
    agents: list[str] | None = None,
    period_from: dt.datetime | None = None,
    period_to: dt.datetime | None = None,
    controls: list[str] | None = None,
    requested_by: str = "system",
    output_dir: Path | None = None,
) -> EvidencePackage:
    """Build an evidence package for a scope of agents × period × controls."""
    settings = get_settings()
    output_dir = output_dir or settings.evidence_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    period_to = period_to or utcnow()
    period_from = period_from or (period_to - dt.timedelta(days=30))
    scope = {
        "agents": agents or ["*"],
        "period_from": _iso(period_from),
        "period_to": _iso(period_to),
        "controls": controls or ["*"],
    }

    # The one page a person reads first. Built before anything is collected,
    # because it computes control status when nobody has — and that should land
    # in control_status.json too, not only in the summary.
    from agentfox.prove.report import build_summary, render_html, render_markdown

    summary = build_summary(session, agents=agents, period_from=period_from, period_to=period_to)

    # --- collect ---------------------------------------------------------
    agent_query = select(Agent)
    if agents and agents != ["*"]:
        agent_query = agent_query.where(Agent.slug.in_(agents))
    agent_rows = list(session.scalars(agent_query))
    agent_slugs = [a.slug for a in agent_rows]

    trace_query = select(Trace).where(
        Trace.started_at >= period_from, Trace.started_at <= period_to
    )
    if agents and agents != ["*"]:
        trace_query = trace_query.where(Trace.agent_slug.in_(agent_slugs))
    traces = list(session.scalars(trace_query.order_by(Trace.started_at)))
    trace_ids = {t.id for t in traces}

    scoped = bool(agents and agents != ["*"])
    agent_ids = {a.id for a in agent_rows}
    # An agent is named by id in some records and by slug in others.
    agent_keys = agent_ids | set(agent_slugs)

    decisions = [
        d
        for d in session.scalars(
            select(Decision).where(
                Decision.created_at >= period_from, Decision.created_at <= period_to
            )
        )
        if not scoped or d.agent_id in agent_ids or (d.trace_id and d.trace_id in trace_ids)
    ]
    decision_ids = {d.id for d in decisions}

    audit_entries = list(
        session.scalars(
            select(AuditEntry)
            .where(AuditEntry.occurred_at >= period_from, AuditEntry.occurred_at <= period_to)
            .order_by(AuditEntry.seq)
        )
    )
    seqs = [e.seq for e in audit_entries]
    checkpoints = list(
        session.scalars(
            select(AuditCheckpoint)
            .where(
                AuditCheckpoint.seq >= (min(seqs) if seqs else 0),
                AuditCheckpoint.seq <= (max(seqs) if seqs else 0),
            )
            .order_by(AuditCheckpoint.seq)
        )
    )

    verification = chain.verify(
        [chain.entry_to_row(e) for e in audit_entries],
        [
            {"seq": c.seq, "digest": c.digest, "signature": c.signature, "key_id": c.key_id}
            for c in checkpoints
        ],
        expect_genesis=bool(seqs) and min(seqs) == 1,
    )

    policy_version_ids = {d.policy_version_id for d in decisions if d.policy_version_id}
    policy_versions = [session.get(PolicyVersion, pid) for pid in policy_version_ids]
    policy_versions = [p for p in policy_versions if p is not None]

    approvals = [
        a
        for a in session.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.requested_at >= period_from,
                ApprovalRequest.requested_at <= period_to,
            )
        )
        if not scoped
        or a.agent_id in agent_ids
        or (a.trace_id and a.trace_id in trace_ids)
        or (a.decision_id and a.decision_id in decision_ids)
    ]
    eval_runs = [
        r
        for r in session.scalars(
            select(EvalRun).where(
                EvalRun.created_at >= period_from, EvalRun.created_at <= period_to
            )
        )
        if not scoped or (r.target_json or {}).get("agent") in agent_keys
    ]
    findings = [
        f
        for f in session.scalars(
            select(Finding).where(
                Finding.created_at >= period_from, Finding.created_at <= period_to
            )
        )
        if not scoped
        or (f.subject_type == "agent" and f.subject_id in agent_keys)
        or (f.subject_type == "trace" and f.subject_id in trace_ids)
        or (f.evidence_json or {}).get("trace_id") in trace_ids
    ]

    # A scoped package must not disclose what other agents did, but dropping their
    # audit entries would leave gaps the verifier reads as deletions. So every entry
    # in the period ships, and an entry about something out of scope ships with its
    # payload withheld: its digests still prove the chain is unbroken, and nothing
    # about the other agent is in the file.
    in_scope_subjects = {
        "agent": agent_keys,
        "trace": trace_ids,
        "decision": decision_ids,
        "finding": {f.id for f in findings},
        "approval": {a.id for a in approvals},
        "eval_run": {r.id for r in eval_runs},
    }
    agent_by_id = {a.id: a.slug for a in session.scalars(select(Agent))}

    def _out_of_scope(entry: AuditEntry) -> bool:
        if not scoped:
            return False
        allowed = in_scope_subjects.get(entry.subject_type)
        if allowed is not None:
            return entry.subject_id not in allowed
        named = (entry.payload_json or {}).get("agent") or (entry.payload_json or {}).get(
            "agent_id"
        )
        if isinstance(named, str) and named:
            return named not in agent_keys and agent_by_id.get(named) not in agent_keys
        return False

    audit_rows = []
    withheld_entries = 0
    for entry in audit_entries:
        row = chain.entry_to_row(entry)
        if _out_of_scope(entry):
            row["payload"] = None
            row["subject_id"] = None
            row["payload_withheld"] = True
            withheld_entries += 1
        audit_rows.append(row)
    statuses = list(
        session.scalars(select(ControlStatus).order_by(ControlStatus.computed_at.desc()))
    )
    if controls and controls != ["*"]:
        statuses = [s for s in statuses if s.control_key in controls]
    risk = list(session.scalars(select(RiskAssessment)))

    # Appendix B §B.6: every mapping ships, draft or reviewed — each one is
    # chip-labeled below so an auditor can see exactly what is still outstanding
    # instead of the gap being invisible.
    mappings = list(session.scalars(select(FrameworkMapping)))
    draft_mappings = [m for m in mappings if m.review_status != "reviewed"]

    # --- serialise -------------------------------------------------------
    files: dict[str, str] = {
        # First in the archive, so it is the first thing anyone opening it sees.
        "SUMMARY.md": render_markdown(summary),
        "SUMMARY.html": render_html(summary),
        "audit_entries.json": json.dumps(audit_rows, indent=2, default=str),
        "audit_checkpoints.json": json.dumps(
            [
                {
                    "seq": c.seq,
                    "digest": c.digest,
                    "signature": c.signature,
                    "key_id": c.key_id,
                    "signed_at": _iso(c.signed_at),
                }
                for c in checkpoints
            ],
            indent=2,
        ),
        "traces.json": json.dumps(
            [full_trace(session, t.id) for t in traces], indent=2, default=str
        ),
        "decisions.json": json.dumps(
            [
                {
                    "id": d.id,
                    "trace_id": d.trace_id,
                    "surface": d.surface,
                    "tool": d.tool_key,
                    "verdict": d.verdict,
                    "mode": d.mode,
                    "policy_version_id": d.policy_version_id,
                    "rules_fired": d.rules_fired_json,
                    "latency_ms": d.latency_ms,
                    "created_at": _iso(d.created_at),
                }
                for d in decisions
            ],
            indent=2,
            default=str,
        ),
        "policy_versions.json": json.dumps(
            [
                {
                    "id": p.id,
                    "policy_id": p.policy_id,
                    "version": p.version,
                    "author": p.author,
                    "created_at": _iso(p.created_at),
                    "body": p.body,
                }
                for p in policy_versions
            ],
            indent=2,
            default=str,
        ),
        "agents.json": json.dumps(
            [
                {
                    "slug": a.slug,
                    "name": a.name,
                    "purpose": a.purpose,
                    "owner": a.owner_email,
                    "risk_tier": a.risk_tier,
                    "environment": a.environment,
                    "framework": a.framework,
                    "registered": a.registered,
                }
                for a in agent_rows
            ],
            indent=2,
        ),
        "approvals.json": json.dumps(
            [
                {
                    "id": a.id,
                    "tool": a.tool_key,
                    "reason": a.reason,
                    "status": a.status,
                    "requested_at": _iso(a.requested_at),
                    "resolver": a.resolver_user_id,
                    "rationale": a.resolution_rationale,
                }
                for a in approvals
            ],
            indent=2,
        ),
        "eval_runs.json": json.dumps(
            [
                {
                    "id": r.id,
                    "suite_id": r.suite_id,
                    "target": r.target_json,
                    "status": r.status,
                    "summary": r.summary_json,
                    "created_at": _iso(r.created_at),
                }
                for r in eval_runs
            ],
            indent=2,
            default=str,
        ),
        "findings.json": json.dumps(
            [
                {
                    "id": f.id,
                    "type": f.type,
                    "severity": f.severity,
                    "status": f.status,
                    "title": f.title,
                    "controls": f.control_keys,
                    "created_at": _iso(f.created_at),
                }
                for f in findings
            ],
            indent=2,
        ),
        "control_status.json": json.dumps(
            [
                {
                    "control_key": s.control_key,
                    "status": s.status,
                    "computed_at": _iso(s.computed_at),
                    "rationale": s.rationale,
                    "evidence": s.evidence_json,
                }
                for s in statuses
            ],
            indent=2,
            default=str,
        ),
        "framework_mappings.json": json.dumps(
            [
                {
                    "control_key": m.control_key,
                    "framework": m.framework,
                    "reference": m.reference,
                    "review_status": m.review_status,
                    "reviewed_by": m.reviewed_by,
                    "chip": (
                        "REVIEWED"
                        if m.review_status == "reviewed"
                        else "DRAFT — UNVERIFIED / NOT LEGAL ADVICE"
                    ),
                }
                for m in mappings
            ],
            indent=2,
        ),
        "risk_assessments.json": json.dumps(
            [
                {
                    "agent_id": r.agent_id,
                    "eu_ai_act_class": r.eu_ai_act_class,
                    "inherent_risk": r.inherent_risk,
                    "residual_risk": r.residual_risk,
                    "assessor": r.assessor,
                    "assessed_at": _iso(r.assessed_at),
                }
                for r in risk
            ],
            indent=2,
            default=str,
        ),
        "chain_verification.json": json.dumps(verification.to_json(), indent=2),
        "verify_chain.py": VERIFIER_SCRIPT,
    }

    files["README.txt"] = _readme(
        scope, verification, len(traces), len(decisions), len(audit_entries), len(draft_mappings)
    )

    manifest = {
        "package_version": "1.0",
        "generated_at": _iso(utcnow()),
        "generated_by": requested_by,
        "code_version": __version__,
        "catalog_version": "0.1.0-draft",
        "scope": scope,
        "counts": {
            "agents": len(agent_rows),
            "traces": len(traces),
            "decisions": len(decisions),
            "audit_entries": len(audit_entries),
            "audit_payloads_withheld": withheld_entries,
            "checkpoints": len(checkpoints),
            "approvals": len(approvals),
            "eval_runs": len(eval_runs),
            "findings": len(findings),
            "control_statuses": len(statuses),
            "reviewed_mappings": len(mappings) - len(draft_mappings),
            "draft_mappings_included": len(draft_mappings),
        },
        "chain_verification": verification.to_json(),
        "files": {
            name: {
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
                "bytes": len(body.encode()),
            }
            for name, body in files.items()
        },
    }
    files["manifest.json"] = json.dumps(manifest, indent=2, default=str)

    record = EvidencePackage(
        scope_json=scope,
        requested_by=requested_by,
        manifest_json=manifest,
        chain_verification_json=verification.to_json(),
        code_version=__version__,
        catalog_version="0.1.0-draft",
    )
    session.add(record)
    session.flush()

    path = output_dir / f"{record.id}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    record.path = str(path)
    session.flush()

    # P5-7 / C.5: producing evidence is itself an audit event. Who looked at the
    # evidence matters as much as what the evidence says.
    chain.append(
        session,
        "evidence.exported",
        actor_type="user",
        actor_id=requested_by,
        subject_type="evidence_package",
        subject_id=record.id,
        payload={"scope": scope, "counts": manifest["counts"], "chain_valid": verification.valid},
    )
    return record


def _readme(
    scope: dict[str, Any],
    verification: chain.VerificationResult,
    traces: int,
    decisions: int,
    entries: int,
    draft_mappings: int,
) -> str:
    status = "INTACT" if verification.valid else "TAMPERED"
    return f"""AGENTFOX EVIDENCE PACKAGE
=========================

Start with SUMMARY.md (or SUMMARY.html): one page, in plain language, on what
was running, what was contained and what is still only observed. Everything
below is the machine-readable record that page is built from.

Scope
-----
Agents   : {", ".join(scope["agents"])}
Period   : {scope["period_from"]} .. {scope["period_to"]}
Controls : {", ".join(scope["controls"])}

Contents
--------
SUMMARY.md / .html       The one-page summary. Its framework coverage section is a
                         DRAFT — UNVERIFIED mapping, labelled as such.
traces.json              Full execution paths: prompts, retrievals, tool calls,
                         delegations, guardrail decisions, errors (control NOM-AUD-01).
decisions.json           Every policy decision with the rules that fired and the
                         exact policy version in force at the time.
policy_versions.json     Those policy versions, verbatim. Policy versions are
                         immutable, so what is here is what was enforced.
audit_entries.json       The tamper-evident audit chain for the period (NOM-AUD-02).
                         In a package scoped to some agents, entries about other
                         agents keep their digests (so the chain still verifies)
                         but carry "payload_withheld": true and no payload.
audit_checkpoints.json   Signed anchors over that chain.
chain_verification.json  Our verification result — see below to check it yourself.
approvals.json           Human-in-the-loop approvals and who resolved them (NOM-IAM-03).
eval_runs.json           Evaluation and regression-gate results (NOM-EVL-01).
findings.json            Governance findings raised in the period.
control_status.json      Control effectiveness computed from telemetry (NOM-GOV-04).
framework_mappings.json  Control-to-framework mappings, reviewed and draft alike —
                         each row carries a "chip" of REVIEWED or DRAFT — UNVERIFIED
                         / NOT LEGAL ADVICE so you can see exactly what is outstanding.
risk_assessments.json    Per-agent risk classification and residual risk.
agents.json              The agent inventory in scope.
manifest.json            SHA-256 of every file above, plus provenance.

Independent verification
------------------------
Do not take our word for the chain. Run, from this directory:

    python3 verify_chain.py

It uses only the Python standard library and re-derives every digest from the
exported rows. To verify the signed checkpoints as well, set AGENTFOX_AUDIT_KEY
(or the older NOMETRIA_AUDIT_KEY) to the checkpoint signing key -- held by the
operator, outside the application database -- before running it.

Our verification result: chain {status}
  entries checked : {verification.entries_checked}
  breaks          : {len(verification.breaks)}
  checkpoints     : {verification.checkpoints_checked}

Scope of this package: {traces} traces, {decisions} decisions, {entries} audit entries.

Important limitations
---------------------
* {draft_mappings} control-to-framework mapping(s) in framework_mappings.json are
  chip-labeled 'DRAFT — UNVERIFIED / NOT LEGAL ADVICE' because they have not
  completed compliance review (only rows chip-labeled 'REVIEWED' have). Draft
  mappings are engineering drafts produced from framework texts and are not legal
  advice — do not present them to an auditor as a completed regulatory claim
  without first running them through the review gate (Appendix B §B.6).
* Control status is computed from observed telemetry for the stated period. A
  control reported 'effective' means its evidence sources were present and its
  rule passed over this scope — not that the control is effective in general.
* Content in traces is redacted at capture. Detector findings record entity type,
  location and a masked sample rather than the underlying sensitive value.
"""
