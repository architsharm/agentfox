import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Compliance",
  description:
    "Controls, frameworks and mapping review, obligations, the risk register, evidence packages and chain verification, retention and legal hold, and the board snapshot. Framework mappings are drafts.",
  path: "/docs/app/compliance",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Compliance</h1>
      <p className="docs-lede">
        One control set mapped to several frameworks, with each control&apos;s status computed
        from your own telemetry rather than attested on a form, and the evidence to show for
        it.
      </p>
      <InTheApp path="/app/compliance">Compliance</InTheApp>

      <Callout kind="warning" title="Every framework mapping is a DRAFT">
        <p>
          The mappings from controls to framework clauses (EU AI Act, NIST AI RMF, ISO/IEC
          42001, SOC 2, OWASP and others) are engineering&apos;s reading of the published texts.
          They have not been reviewed by compliance counsel or a certification body, and they
          are not legal advice. The page says so in a one-line Draft note on every tab.
        </p>
        <p>
          Evidence packages include every mapping, and each one not yet reviewed by a named
          person is stamped <strong>DRAFT — UNVERIFIED / NOT LEGAL ADVICE</strong>. A computed
          &quot;effective&quot; status means the telemetry supports the control, not that you are
          compliant with a regulation.
        </p>
      </Callout>

      <h2>When to use this</h2>
      <ul>
        <li>To see which controls the telemetry says are failing, and why.</li>
        <li>To have a qualified person review mappings framework by framework.</li>
        <li>To build an evidence package for an auditor, and to place a legal hold.</li>
        <li>To give leadership a one-page snapshot.</li>
      </ul>

      <h2>The header</h2>
      <p>
        The page loads <code>GET /api/controls</code>, <code>/api/frameworks</code>,{" "}
        <code>/api/obligations</code>, <code>/api/risk/register</code>,{" "}
        <code>/api/evidence</code> and <code>/api/retention</code>. Above the tabs: the Draft
        note, and a bar of control statuses (effective, degraded, failing, not implemented, not
        computed) with the effectiveness percentage. Not-implemented controls are left out of
        the ratio, not counted as failing. If the control catalog was never loaded, a{" "}
        <strong>Load control catalog</strong> button appears (<code>POST /api/controls/sync</code>);
        workspaces created by GitHub sign-in have it loaded already.
      </p>

      <h2>Controls tab</h2>
      <p>
        A worklist first: the failing and degraded controls, with what the telemetry found.
        Then the full catalogue (collapsed): each control&apos;s title and key, what it checks,
        status and the evidence or rationale. Grey means not assessed, which is different from
        failing. <strong>Recompute status from telemetry</strong> (
        <code>POST /api/controls/compute</code>) re-runs the assessment; controls that were never
        computed need real traffic, not a click.
      </p>
      <Code>{`agentfox report status`}</Code>
      <Output>{`all frameworks — 43 controls
  36 effective · 0 degraded · 4 failing · 2 not implemented
  effectiveness 90%`}</Output>

      <h2>Regulations tab</h2>
      <p>
        One row per framework: how many requirements (cited articles or clauses) the
        controls answer, how many of those controls are effective, failing or degraded, how
        many carry a current review, and the next dated obligation. Each row opens{" "}
        <code>/app/compliance/frameworks/&lt;key&gt;</code> (<code>GET /api/frameworks/&#123;key&#125;</code>):
        every requirement with the controls mapped to it, each control&apos;s computed status
        and review, the framework&apos;s deadlines with the agents in scope, and what it does
        not cover.
      </p>

      <h2 id="reviews">Reviewing a control</h2>
      <p>
        A control row opens <code>/app/compliance/controls/&lt;key&gt;</code> (
        <code>GET /api/controls/&#123;key&#125;</code>): its computed status and rationale, the
        bound rules that implement it with when each last fired, the runs they acted on, open
        findings, and evidence packages that cover it. <strong>Record a review</strong> is a
        named attestation against one framework: an outcome (meets, partially meets, does not
        meet, not applicable) and a note, required for anything short of meets. It posts{" "}
        <code>POST /api/controls/&#123;key&#125;/reviews</code> and needs owner, admin,
        compliance or auditor. The reviewer is always you.
      </p>
      <p>
        A review freezes the evidence shown at that moment onto the review, is recorded on the
        audit chain as <code>compliance.control_reviewed</code>, and expires after 90 days,
        when it reads <code>Review expired</code> until someone reviews again. Evidence
        packages carry every review in <code>control_reviews.json</code>.
      </p>
      <p>
        The CLI writes everything a reviewer needs for one framework into one file:
      </p>
      <Code>{`agentfox report review-packet --framework eu-ai-act --out eu-ai-act-review.md`}</Code>

      <h2 id="risk">Risk register tab</h2>
      <p>
        One row per agent: risk tier, EU AI Act class (or <code>not assessed</code>), residual
        risk, assessor, next review (or <code>overdue</code>). <strong>Assess</strong> /{" "}
        <strong>Reassess</strong> opens a form: EU AI Act class (or &quot;Let the platform propose
        one&quot;), residual risk (low, medium, high) and who signed it off.{" "}
        <strong>Record assessment</strong> posts <code>POST /api/risk/assessments/&#123;slug&#125;</code>{" "}
        and needs owner, admin or compliance. <code>agentfox report risk</code> prints the
        register.
      </p>

      <h2 id="evidence">Evidence &amp; reports tab</h2>
      <ul>
        <li>
          <strong>Verify audit chain integrity now</strong> (<code>POST /api/audit/verify</code>)
          re-derives the hash chain over every audit entry and reports the result as a notice:
        </li>
      </ul>
      <Output>{`chain verified — 95 entries (seq 1–95), 1 checkpoint(s), intact`}</Output>
      <ul>
        <li>
          <strong>Build a package</strong>: agents (comma-separated slugs, blank for all),
          controls (blank for all), period from and to. <strong>Build evidence package</strong>{" "}
          posts <code>POST /api/evidence</code>; building needs owner, admin, security,
          compliance or auditor.
        </li>
        <li>
          <strong>The packages table</strong>: when built, by whom, scope, chain{" "}
          <code>verified</code> or <code>broken</code>, counts of what is inside (an empty
          package is tagged as such), and <strong>Download →</strong> (
          <code>GET /api/evidence/&#123;id&#125;/download</code>, a zip).
        </li>
      </ul>
      <Output title="Files in the downloaded zip">{`SUMMARY.md  SUMMARY.html  audit_entries.json  audit_checkpoints.json  traces.json
decisions.json  policy_versions.json  agents.json  approvals.json  eval_runs.json
findings.json  control_status.json  framework_mappings.json  risk_assessments.json
chain_verification.json  verify_chain.py  README.txt  manifest.json`}</Output>
      <p>
        The recipient verifies it without trusting AgentFox or calling its API:
      </p>
      <Code>{`python3 verify_chain.py`}</Code>
      <Output>{`note: AGENTFOX_AUDIT_KEY not set - checkpoint signatures not verified
entries checked: 95 (seq 1..95)
CHAIN INTACT`}</Output>
      <Callout kind="note" title="What the agent field narrows">
        Naming agents limits the inventory, traces, decisions, findings, approvals and eval
        runs to those agents. The audit chain still covers the whole period, because a gap
        would read as a deletion; entries about other agents ship with their payload and
        subject withheld (<code>&quot;payload_withheld&quot;: true</code>), and{" "}
        <code>verify_chain.py</code> still checks their linkage.
      </Callout>
      <Code>{`agentfox report evidence --agent payments-ops --since-days 30
agentfox report verify`}</Code>
      <Output>{`evidence package
…/state/var/evidence/evd_01m469zq7njq66qhsx.zip
  period                   2026-09-05 → 2026-10-05
  agents                   1
  traces                   0
  decisions                3
  audit entries            27
  audit payloads withheld  22
…
  chain verification       valid

Verify independently: unzip, then \`python3 verify_chain.py\`
chain: 99 entries, head seq 99, 1 checkpoints
CHAIN INTACT — 99 entries verified (seq 1..99)`}</Output>
      <p>
        Building a package is logged to the audit chain after its contents are computed, so a
        package is always one entry behind a verification run straight after it. (The tab
        shows the older command name for building one; the current one is above.)
      </p>

      <h2>Retention &amp; legal hold tab</h2>
      <p>
        Each data class (prompt and response content, detection samples, runs, decisions,
        evaluation output, and the audit log), how long it is kept and what happens after:
        deleted, or content redacted with the record kept. <strong>Change</strong> sets the
        period with a required reason (<code>PUT /api/retention/&#123;class&#125;</code>, owner,
        admin or compliance), recorded on the audit chain with the before and after. The audit
        log is locked: it cannot be given a period and is never purged.
      </p>
      <p>
        A daily job, <code>retention.purge</code>, applies every period. A class with no period
        is kept. An active legal hold wins: a hold with no agents stops the purge, an
        agent-scoped hold keeps that agent&apos;s data. Each pass is recorded (
        <code>GET /api/retention/runs</code>) and on the audit chain as{" "}
        <code>retention.purged</code>. The tab shows the last purge and the next one;{" "}
        <strong>Run purge now</strong> posts <code>POST /api/retention/purge</code>.
      </p>
      <p>
        <strong>Place a hold</strong> takes agents (blank for all) and a required reason, and
        posts <code>POST /api/legal-holds</code> (owner, admin or compliance). Holds are listed
        with who placed them, scope, reason and whether they are active.
      </p>

      <h2>Board snapshot tab</h2>
      <p>
        <code>/app/compliance?tab=board</code> (<code>GET /api/board</code>): a printable
        one-page view, generated when you open it and not live. Tiles appear only for what
        wants attention: high-risk agents, unregistered agents, unassessed agents, open
        findings. Then agents under management, control effectiveness, agents by risk class,
        open findings by severity, control effectiveness per framework, and the regulatory
        clock (live and upcoming obligations with days remaining). It says how many agents are
        sample data, and ends with the draft caveat. <strong>Print / save as PDF</strong> opens the browser&apos;s print dialog.
      </p>
      <Code>{`agentfox report board`}</Code>
      <Output>{`╭─────────────────╮
│ AI risk posture │
╰─────────────────╯
  agents under management  6 (1 shadow, 3 unowned)
  high-risk agents         1 ['payments-ops']
…
  open findings            24 {'critical': 9, 'high': 5, 'medium': 10}
  controls with evidence   36 of 43 effective (40 assessed, 2 with no evidence yet)
  live obligations         2
  upcoming (24mo)          5

Control statuses are computed from telemetry over the stated window. Framework mappings are DRAFT
and have not been reviewed by compliance counsel — see the coverage and gap declarations per
framework.`}</Output>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "Control status", run: "agentfox report status" },
          { task: "Recompute control status", run: "agentfox admin catalog compute" },
          { task: "Frameworks and review status", run: "agentfox report frameworks" },
          { task: "Hand a reviewer one framework", run: "agentfox report review-packet --framework eu-ai-act --out review.md" },
          { task: "Build an evidence package", run: "agentfox report evidence --since-days 30" },
          { task: "Verify the audit chain", run: "agentfox report verify" },
          { task: "Board snapshot in a terminal", run: "agentfox report board" },
          { task: "Risk register / obligations", run: "agentfox report risk" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>Every count reads zero.</strong> The catalog is not loaded; press Load control
          catalog, or run <code>agentfox admin catalog sync</code>.
        </li>
        <li>
          <strong>Controls stay &quot;not computed&quot; after Recompute.</strong> They need
          telemetry that does not exist yet.
        </li>
        <li>
          <strong>The chain shows <code>broken</code>.</strong> An audit entry was altered or
          removed after it was written. The notice names the first broken sequence number.
        </li>
        <li>
          <strong>The board snapshot&apos;s &quot;Overview&quot; link opens the public home
          page</strong>, not the app&apos;s Overview. Use the sidebar.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>Mappings are drafts until reviewed, and reviewed mappings are your reviewer&apos;s claim, not AgentFox&apos;s.</li>
        <li>No retention schedules from the web app; no legal-hold release button.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/guides/audit-evidence", label: "Prove it to an auditor", why: "the report, packages and sign-off" },
          { href: "/docs/limits", label: "Limits", why: "what the evidence cannot show" },
          { href: "/docs/app/findings", label: "Findings", why: "what failing controls point at" },
        ]}
      />
    </article>
  );
}
