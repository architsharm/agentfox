"""End-to-end walkthrough — the "it just caught something" moment.

The product should *demo itself*: a blocked injection and a trace a CISO can read
beats any deck. This script walks the full request path and prints what each pillar
contributed, using only the offline provider.

Every number printed here is computed live from the same code paths the product uses.
Nothing is narrated that did not actually happen.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentfox.cli._style import SEVERITY_COLOUR
from agentfox.core.db import session_scope
from agentfox.core.models import AuditEntry, EvalSuite, Finding
from agentfox.evaluation import gate, run_campaign, set_baseline
from agentfox.evaluation.runner import NativeEvalRunner
from agentfox.fixtures.seed import POISONED_DOCUMENT
from agentfox.platform.identity import assess_posture
from agentfox.platform.policy import set_mode
from agentfox.platform.registry.service import (
    attest_registry,
    derive_lineage,
    detect_shadow_agents,
    lineage,
    unowned_agents,
)
from agentfox.prove.audit import chain, evidence
from agentfox.prove.audit.trace import full_trace
from agentfox.prove.compliance import compute_all, posture
from agentfox.runtime.enforcement import Enforcer

console = Console()


def _rule(title: str, number: str) -> None:
    console.print()
    console.rule(f"[bold cyan]{number}[/] · [bold]{title}[/]", style="cyan")


def _verdict_style(verdict: str) -> str:
    return {
        "block": "bold red",
        "escalate": "bold yellow",
        "redact": "yellow",
        "tokenize": "yellow",
        "mask": "yellow",
        "allow": "green",
    }.get(verdict, "white")


def _rule_modes(session) -> dict[str, tuple[str, str]]:
    """``rule_id -> (policy key, that policy's mode)`` for every bound policy.

    Several packs are bound at once and they are not all in the same mode. The
    merged decision carries one mode — "enforce" if *any* bound pack enforces — so
    printing it next to a rule that came from a pack in observe said the opposite of
    what happened. This is the lookup that lets each rule say its own mode.
    """
    from agentfox.platform.policy import active_policies

    out: dict[str, tuple[str, str]] = {}
    for document, _version, _binding in active_policies(session):
        for rule in document.rules:
            out[rule.id] = (document.key, document.mode)
    return out


def _show(result, label: str, session=None) -> None:
    console.print(
        f"  [bold]{label}[/]  "
        f"enforced=[{_verdict_style(result.verdict)}]{result.verdict}[/]  "
        f"policy-would=[{_verdict_style(result.effective_verdict)}]{result.effective_verdict}[/]  "
        f"[dim]{result.latency_ms:.1f}ms[/]"
    )
    modes = _rule_modes(session) if (session is not None and result.rules_fired) else {}
    for rule in result.rules_fired:
        rule_id = rule.get("rule_id")
        pack, mode = modes.get(rule_id, ("", ""))
        # The mode that decided this rule's effect, not the mode of the merged set.
        where = f"  [dim]{pack} is in {mode}[/]" if mode else ""
        console.print(f"      [magenta]{rule_id}[/] → {rule.get('effect')}{where}")
        console.print(f"        [dim]{rule.get('reason', '')[:110]}[/]")
        if rule.get("controls"):
            console.print(f"        [dim]controls: {', '.join(rule['controls'])}[/]")
    if result.entities:
        console.print(f"      [dim]detected: {', '.join(result.entities)}[/]")


def _steady_state_spans(session, exclude_trace: str) -> dict[str, float]:
    """Median duration per span name across every *other* trace in this database.

    Measured, not asserted: the comparison a "one-time warm-up" claim needs is the
    same span on the calls that did not pay for it. The median rather than the
    minimum, so one unusually fast call cannot flatter the number.
    """
    from statistics import median

    from sqlalchemy import select

    from agentfox.core.models import Span

    grouped: dict[str, list[float]] = {}
    for span in session.scalars(select(Span).where(Span.trace_id != exclude_trace)):
        grouped.setdefault(span.name, []).append(span.duration_ms)
    return {name: median(values) for name, values in grouped.items() if values}


#: How many times slower than its steady state a span has to be before it is called a
#: cold start rather than ordinary variance.
COLD_START_FACTOR = 5


def _span_line(span: dict[str, Any], steady: dict[str, float]) -> tuple[str, bool]:
    """One span row, and whether it was a cold start.

    The trace the walkthrough prints is the first call of the process, so its
    guardrail spans also paid for loading every detector. Printing 3500ms here next
    to section 01's 3ms for the same call read as a contradiction. It is a cold
    start, and the number a reader needs is the one every later call gets.
    """
    later = steady.get(span["name"])
    cold = later is not None and span["duration_ms"] > later * COLD_START_FACTOR
    note = f"  [yellow]first call only, {later:.1f}ms once warm[/]" if cold else ""
    return (
        f"    [dim]{span['kind']:<10}[/] {span['name']:<28} "
        f"[dim]{span['duration_ms']:.1f}ms[/]{note}",
        cold,
    )


def _shared_control_count(session, frameworks: tuple[str, ...]) -> int:
    """How many controls every one of these frameworks maps, when that is all of them.

    Returns 0 when the frameworks cover different control sets, so the explanation
    printed next to the posture table is only printed when it is true of this catalog.
    """
    from sqlalchemy import select

    from agentfox.core.models import Control, FrameworkMapping

    every_control = set(session.scalars(select(Control.key)))
    if not every_control:
        return 0
    for framework in frameworks:
        mapped = {
            m.control_key
            for m in session.scalars(
                select(FrameworkMapping).where(FrameworkMapping.framework == framework)
            )
        }
        if not every_control <= mapped:
            return 0
    return len(every_control)


#: Step 08 promotes this policy to enforce to show the difference. The promotion is
#: part of the show, not a configuration change: `run` puts it back afterwards.
DEMO_PROMOTED_POLICY = "baseline"


def _current_mode(key: str) -> str | None:
    """The mode of the open binding on a policy's latest version, or None."""
    from sqlalchemy import select

    from agentfox.core.models import Policy, PolicyBinding, PolicyVersion

    with session_scope() as session:
        policy = session.scalar(select(Policy).where(Policy.key == key))
        if policy is None:
            return None
        latest = session.scalars(
            select(PolicyVersion)
            .where(PolicyVersion.policy_id == policy.id)
            .order_by(PolicyVersion.version.desc())
        ).first()
        if latest is None:
            return None
        binding = session.scalars(
            select(PolicyBinding).where(
                PolicyBinding.policy_version_id == latest.id,
                PolicyBinding.effective_to.is_(None),
            )
        ).first()
        return binding.mode if binding else None


def run() -> dict[str, Any]:
    """Run the walkthrough. Returns a summary so tests can assert on it.

    A demo must not leave the deployment more restrictive than it found it, so the
    promoted policy's previous mode is restored even if a step raises.
    """
    previous = _current_mode(DEMO_PROMOTED_POLICY)
    try:
        return _walkthrough()
    finally:
        if previous is not None and _current_mode(DEMO_PROMOTED_POLICY) != previous:
            with session_scope() as session:
                set_mode(session, DEMO_PROMOTED_POLICY, previous)
            console.print(
                f"[dim]{DEMO_PROMOTED_POLICY} policy restored to {previous} — "
                "the demo's promotion was temporary.[/]"
            )


def _walkthrough() -> dict[str, Any]:
    summary: dict[str, Any] = {}

    console.print(
        Panel.fit(
            "[bold]AgentFox Control Plane — end-to-end walkthrough[/]\n"
            "[dim]Offline: no API key, no model weights, no network egress.[/]",
            border_style="cyan",
        )
    )

    # ---------------------------------------------------------------
    _rule("A normal call — allowed, traced, audited", "01")
    with session_scope() as session:
        enforcer = Enforcer(session)
        result, response = enforcer.run_completion(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "How long do I have to request a refund?"}],
            intent="answer a customer refund question",
            model="echo-1",
        )
        _show(result, "user question", session)
        console.print(f"  [green]response[/] {response.text if response else '—'}")
        console.print(f"  [dim]trace {result.trace_id}[/]")
        summary["normal_verdict"] = result.verdict
        normal_trace = result.trace_id

    # ---------------------------------------------------------------
    _rule("Indirect prompt injection via a retrieved document", "02")
    console.print(
        "  [dim]The payload is not in the user's message. It arrives inside a document "
        "the agent retrieved — the highest-severity realistic attack on an agent.[/]"
    )
    with session_scope() as session:
        result, _ = Enforcer(session).run_completion(
            agent_slug="support-triage",
            messages=[
                {"role": "user", "content": "Summarise the Q3 refunds document."},
                {"role": "tool", "content": POISONED_DOCUMENT},
            ],
            intent="summarise the Q3 refunds document",
            model="echo-1",
        )
        _show(result, "retrieved document", session)
        console.print(
            "  [dim]The baseline policy ships in observe mode, so the call was not "
            "blocked — but the platform recorded exactly what it would have done. "
            "That is the intended default (false blocks are how guardrails get "
            "switched off).[/]"
        )
        summary["injection_effective"] = result.effective_verdict
        summary["injection_entities"] = result.entities

    # ---------------------------------------------------------------
    _rule("Containment: the injection reaches a tool, and is stopped anyway", "03")
    console.print(
        "  [dim]Assume detection failed and the model was fully persuaded. The "
        "account number still came from an untrusted document, and an irreversible "
        "tool may not take untrusted arguments.[/]"
    )
    with session_scope() as session:
        enforcer = Enforcer(session)
        clean = enforcer.guard_tool_call(
            agent_slug="payments-ops",
            tool_key="payments.transfer",
            arguments={"amount": 250, "currency": "USD", "to": "acct_customer_44"},
            intent="refund a duplicate charge",
        )
        _show(clean, "transfer, argument from the user", session)

        tainted = enforcer.guard_tool_call(
            agent_slug="payments-ops",
            tool_key="payments.transfer",
            arguments={"amount": 250, "currency": "USD", "to": "acct_attacker_991"},
            provenance={"to": "tool_result"},
            intent="refund a duplicate charge",
        )
        _show(tainted, "transfer, recipient from the poisoned document", session)
        console.print(
            f"  [bold yellow]→ suspended pending human approval ({tainted.approval_id})[/]"
        )
        summary["tainted_verdict"] = tainted.verdict
        summary["approval_id"] = tainted.approval_id

        over = enforcer.guard_tool_call(
            agent_slug="payments-ops",
            tool_key="payments.transfer",
            arguments={"amount": 25000, "currency": "USD", "to": "acct_x"},
            intent="settle an invoice",
        )
        _show(over, "transfer above the capability's argument constraint", session)
        summary["over_limit_verdict"] = over.verdict

    # ---------------------------------------------------------------
    _rule("Shadow agent — traffic nobody registered", "04")
    with session_scope() as session:
        Enforcer(session).run_completion(
            agent_slug="marketing-copy-bot",
            messages=[{"role": "user", "content": "Draft a launch email."}],
            model="echo-1",
            environment="production",
        )
        # The full discovery sweep: shadow agents, unowned agents, registry drift,
        # identity posture. Each produces a finding rather than a dashboard number.
        unowned = unowned_agents(session)
        drift = attest_registry(session)
        posture_findings = assess_posture(session)
        shadows = detect_shadow_agents(session)
        table = Table(box=None, pad_edge=False)
        table.add_column("agent", style="bold")
        table.add_column("env")
        table.add_column("calls", justify="right")
        table.add_column("first seen", style="dim")
        for shadow in shadows:
            table.add_row(
                shadow["slug"],
                shadow["environment"],
                str(shadow["calls"]),
                (shadow["first_seen"] or "")[:19],
            )
        console.print(table)
        console.print(
            "  [dim]Detected from gateway traffic, not from anyone filling in a form. "
            "Each finding carries a ready-to-submit registration payload.[/]"
        )
        console.print(
            f"  sweep: [red]{len(shadows)} shadow[/] · "
            f"[yellow]{len(unowned)} unowned[/] · "
            f"[yellow]{len(drift)} registry drift[/] · "
            f"[yellow]{len(posture_findings)} identity posture[/]"
        )
        summary["shadow_agents"] = [s["slug"] for s in shadows]
        summary["unowned_agents"] = len(unowned)

    # ---------------------------------------------------------------
    _rule("PII leaving the agent — graded by sensitivity", "05")
    with session_scope() as session:
        enforcer = Enforcer(session)
        ordinary = enforcer.check_content(
            agent_slug="support-triage",
            content="I've found the account — the contact address is jane.doe@example.com.",
            surface="output",
        )
        console.print(
            f"  [bold]contact detail[/]  "
            f"policy-would=[{_verdict_style(ordinary['effective_verdict'])}]"
            f"{ordinary['effective_verdict']}[/]  "
            f"[dim]{', '.join(ordinary['entities'])}[/]"
        )
        sensitive = enforcer.check_content(
            agent_slug="support-triage",
            content=("Customer jane.doe@example.com, SSN 123-45-6789, card 4111 1111 1111 1111."),
            surface="output",
        )
        console.print(
            f"  [bold]national identifier[/]  "
            f"policy-would=[{_verdict_style(sensitive['effective_verdict'])}]"
            f"{sensitive['effective_verdict']}[/]  "
            f"[dim]{', '.join(sensitive['entities'])}[/]"
        )
        console.print(
            "  [dim]Ordinary personal data is redacted so the response still works; "
            "national identifiers and card numbers are blocked outright. The graded "
            "response is what stops a DLP control from becoming an outage.[/]"
        )
        summary["pii_entities"] = sensitive["entities"]
        summary["pii_ordinary_verdict"] = ordinary["effective_verdict"]
        summary["pii_sensitive_verdict"] = sensitive["effective_verdict"]

    # ---------------------------------------------------------------
    _rule("Silent failure — the plausible, confident, wrong answer", "06")
    console.print(
        "  [dim]No safety filter flags this. No schema check flags it. It is fluent, "
        "specific and completely wrong.[/]"
    )
    with session_scope() as session:
        suite = session.query(EvalSuite).filter_by(key="support-quality").one()
        runner = NativeEvalRunner()
        run_result = runner.run(
            session,
            suite,
            {"provider": "echo", "model": "echo-1"},
            ["groundedness", "task_completion", "hedging", "silent_failure", "contains"],
        )
        scorers = (run_result.summary_json or {}).get("scorers", {})

        table = Table(box=None, pad_edge=False)
        table.add_column("scorer", style="bold")
        table.add_column("mean", justify="right")
        table.add_column("pass rate", justify="right")
        for key, stats in scorers.items():
            rate = stats.get("pass_rate")
            table.add_row(key, f"{stats['mean']:.3f}", f"{rate:.0%}" if rate is not None else "—")
        console.print(table)

        flagged = run_result.summary_json.get("failing_count", 0)
        console.print(
            f"  [bold red]{flagged}[/] of {run_result.summary_json.get('cases')} cases "
            "flagged by the silent-failure ensemble."
        )
        summary["eval_scorers"] = scorers
        summary["eval_failing"] = flagged

        set_baseline(session, run_result, "main", {"silent_failure": 0.05})
        gate_result = gate(session, run_result, run_result.id, min_pass_rate=0.9)
        console.print(
            f"  CI gate: "
            f"[{'green' if gate_result.passed else 'bold red'}]"
            f"{'PASS' if gate_result.passed else 'FAIL'}[/]  "
            f"[dim](exit code {gate_result.exit_code})[/]"
        )
        for failure in gate_result.absolute_failures[:4]:
            console.print(f"      [red]{failure['message']}[/]")
        summary["gate_passed"] = gate_result.passed

    # ---------------------------------------------------------------
    _rule("Red team — probing the deployed configuration", "07")
    with session_scope() as session:
        campaign = run_campaign(session, "support-triage", name="demo sweep")
        stats = campaign.summary_json
        console.print(
            f"  probes: [bold]{stats['probes_run']}[/]  "
            f"blocked: [green]{stats['attacks_blocked']}[/]  "
            f"got through: [red]{stats['attacks_succeeded']}[/]  "
            f"posture: [bold]{stats['posture_score']:.0%}[/]"
        )
        table = Table(box=None, pad_edge=False)
        table.add_column("category", style="bold")
        table.add_column("run", justify="right")
        table.add_column("blocked", justify="right")
        table.add_column("succeeded", justify="right")
        for category, counts in stats["by_category"].items():
            table.add_row(
                category,
                str(counts["run"]),
                str(counts["blocked"]),
                f"[red]{counts['succeeded']}[/]" if counts["succeeded"] else "0",
            )
        console.print(table)
        console.print(
            "  [dim]Probes run through the real enforcement path, so the score "
            "describes the deployed configuration — not a detector in isolation.[/]"
        )
        summary["redteam"] = stats

    # ---------------------------------------------------------------
    _rule("Enforcement on — promoting the baseline policy", "08")
    with session_scope() as session:
        set_mode(session, "baseline", "enforce")
        console.print("  [dim]baseline policy promoted from observe → enforce[/]")
    with session_scope() as session:
        result, _ = Enforcer(session).run_completion(
            agent_slug="support-triage",
            messages=[
                {"role": "user", "content": "Summarise the Q3 refunds document."},
                {"role": "tool", "content": POISONED_DOCUMENT},
            ],
            intent="summarise the Q3 refunds document",
            model="echo-1",
        )
        _show(result, "the same injection, now enforced", session)
        summary["enforced_verdict"] = result.verdict

    # ---------------------------------------------------------------
    _rule("The execution path a CISO can read", "09")
    with session_scope() as session:
        detail = full_trace(session, normal_trace)
        if detail:
            console.print(
                f"  trace [bold]{detail['trace']['id']}[/]  "
                f"agent={detail['trace']['agent']}  "
                f"verdict={detail['trace']['verdict']}"
            )
            # This is the *first* call of the run, so its guardrail spans also paid for
            # loading every detector. Printing 3500ms here next to section 01's 3ms for
            # the same call reads as a contradiction; it is a cold start, and the number
            # a reader needs is the one every later call gets.
            steady = _steady_state_spans(session, exclude_trace=normal_trace)
            lines = [_span_line(span, steady) for span in detail["spans"]]
            warmed = any(cold for _text, cold in lines)
            for text, _cold in lines:
                console.print(text)
            if warmed:
                console.print(
                    "  [dim]Detectors are loaded on the first call of the process. The "
                    "warm figure is the median of the same span across every other "
                    "call recorded in this database.[/]"
                )
            console.print(
                f"  decisions: {len(detail['decisions'])}  "
                f"detector runs: {len(detail['detector_runs'])}  "
                f"taint marks: {len(detail['taint'])}"
            )

        derive_lineage(session)
        graph = lineage(session, "payments-ops")
        console.print(
            f"  lineage for payments-ops: {len(graph['nodes'])} nodes, "
            f"blast radius {graph['blast_radius']}"
        )
        summary["lineage_nodes"] = len(graph["nodes"])

    # ---------------------------------------------------------------
    _rule("Tamper-evident audit — verify, then try to alter history", "10")
    with session_scope() as session:
        stats = chain.chain_stats(session)
        before = chain.verify_range(session)
        console.print(f"  chain: {stats['entries']} entries, head seq {stats['head_seq']}")
        console.print(
            f"  verification: [{'green' if before.valid else 'red'}]"
            f"{'INTACT' if before.valid else 'BROKEN'}[/]  "
            f"({before.entries_checked} entries checked)"
        )
        summary["chain_valid_before"] = before.valid

    with session_scope() as session:
        target = session.query(AuditEntry).filter(AuditEntry.seq == 3).one_or_none()
        if target is not None:
            original = dict(target.payload_json or {})
            target.payload_json = {**original, "verdict": "allow", "tampered": True}
            session.flush()
            after = chain.verify_range(session)
            console.print(
                f"  [red]after editing entry 3 directly in the database:[/] "
                f"[{'green' if after.valid else 'bold red'}]"
                f"{'INTACT' if after.valid else 'TAMPERED'}[/]"
            )
            if after.first_break:
                console.print(
                    f"      [red]seq {after.first_break.seq} · {after.first_break.kind}[/] "
                    f"— {after.first_break.detail}"
                )
            summary["chain_valid_after_tamper"] = after.valid
            target.payload_json = original  # restore so evidence export is clean
            session.flush()

    # ---------------------------------------------------------------
    _rule("Continuous compliance — status computed, not attested", "11")
    with session_scope() as session:
        compute_all(session, window_days=30)
        overall = posture(session)
        table = Table(box=None, pad_edge=False)
        table.add_column("framework", style="bold")
        table.add_column("controls", justify="right")
        table.add_column("effective", justify="right", style="green")
        table.add_column("degraded", justify="right", style="yellow")
        table.add_column("failing", justify="right", style="red")
        table.add_column("not impl.", justify="right", style="dim")
        frameworks = ("eu-ai-act", "nist-ai-rmf", "iso-42001", "soc2")
        for framework in frameworks:
            p = posture(session, framework)
            counts = p["counts"]
            table.add_row(
                framework,
                str(p["controls"]),
                str(counts["effective"]),
                str(counts["degraded"]),
                str(counts["failing"]),
                str(counts["not_implemented"]),
            )
        console.print(table)
        # The rows look copy-pasted and are not. Saying why costs one line and is
        # cheaper than a reader deciding the table is filler — and the reason is
        # checked against the mappings rather than asserted.
        shared = _shared_control_count(session, frameworks)
        if shared:
            console.print(
                f"  [dim]The rows match because all {shared} controls map into every "
                "one of these frameworks: one control answers a clause in each, so the "
                "same telemetry decides its status four times.[/]"
            )
        console.print(
            f"  overall control effectiveness: [bold]{(overall['effectiveness'] or 0):.0%}[/]"
        )
        console.print(
            "  [dim]Every status is derived from telemetry — detector coverage, "
            "decision coverage, chain verification — not from an attestation form. "
            "Framework mappings are DRAFT and ship in evidence packages chip-labeled "
            "DRAFT — UNVERIFIED / NOT LEGAL ADVICE.[/]"
        )
        summary["posture"] = overall

    # ---------------------------------------------------------------
    _rule("Evidence package — verifiable without us", "12")
    with session_scope() as session:
        # Anchor the chain before exporting, so the package carries a signed
        # checkpoint an auditor can validate independently.
        anchor = chain.checkpoint_now(session)
        if anchor is not None:
            console.print(
                f"  [dim]signed checkpoint at seq {anchor.seq} ({anchor.digest[:16]}…)[/]"
            )
        package = evidence.build(
            session,
            agents=["*"],
            period_from=dt.datetime.now(dt.UTC) - dt.timedelta(days=1),
            requested_by="aisha@example.com",
        )
        counts = package.manifest_json["counts"]
        console.print(f"  [bold]{package.path}[/]")
        table = Table(box=None, pad_edge=False)
        table.add_column("contents", style="dim")
        table.add_column("", justify="right")
        for key, value in counts.items():
            table.add_row(key.replace("_", " "), str(value))
        console.print(table)
        verification = package.chain_verification_json
        console.print(
            f"  chain verification embedded: "
            f"[{'green' if verification.get('valid') else 'red'}]"
            f"{'valid' if verification.get('valid') else 'INVALID'}[/]"
        )
        console.print(
            "  [dim]Includes verify_chain.py — stdlib only, re-derives every digest "
            "from the exported rows. An auditor does not have to trust us.[/]"
        )
        summary["evidence_path"] = package.path
        summary["evidence_counts"] = counts

    # ---------------------------------------------------------------
    _rule("Open findings", "13")
    with session_scope() as session:
        findings = list(
            session.query(Finding).filter_by(status="open").order_by(Finding.created_at.desc())
        )
        table = Table(box=None, pad_edge=False)
        table.add_column("severity", style="bold")
        table.add_column("type")
        table.add_column("title")
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for finding in sorted(findings, key=lambda f: order.get(f.severity, 9))[:12]:
            colour = SEVERITY_COLOUR.get(finding.severity, "dim")
            table.add_row(f"[{colour}]{finding.severity}[/]", finding.type, finding.title[:78])
        console.print(table)
        summary["open_findings"] = len(findings)

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Walkthrough complete.[/]\n"
            "[dim]agentfox serve[/]      control plane on :8080\n"
            "[dim]agentfox report verify[/]  re-check the chain\n"
            "[dim]agentfox report evidence --agent payments-ops[/]",
            border_style="green",
        )
    )
    return summary
