import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Findings",
  description:
    "The findings queue and the finding page: filters, severities, finding types, contained versus would-have-been, the evidence panel, resolving and suppressing.",
  path: "/docs/app/findings",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Findings</h1>
      <p className="docs-lede">
        A finding is a problem that needs a person: a detector catch, a refused tool call, an
        unregistered agent, a red-team probe that got through. This is the queue you work
        them from.
      </p>
      <InTheApp path="/app/findings">Findings</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>Daily triage: open findings, most severe first.</li>
        <li>After promoting a policy, to see what it now stops.</li>
        <li>To record that something was fixed, or that it is accepted and why.</li>
      </ul>

      <h2>The queue</h2>
      <p>
        <code>/app/findings</code> loads <code>GET /api/findings?status=…&amp;severity=…&amp;agent=…&amp;limit=200</code>.
        The filters are in the URL, so a filtered view can be bookmarked or linked:
      </p>
      <ul>
        <li><strong>status</strong>: <code>open</code> (the default), <code>resolved</code>, <code>suppressed</code></li>
        <li><strong>severity</strong>: <code>critical</code>, <code>high</code>, <code>medium</code>, <code>low</code>, with <strong>clear severity ×</strong></li>
        <li><strong>agent</strong>: a drop-down and <strong>filter</strong>, with <strong>clear agent ×</strong></li>
      </ul>
      <p>
        Each row shows severity, agent (or &quot;unattributed&quot;), type, title with a
        one-line explanation of the type, the controls it maps to, and when it was raised.
        The caret expands the evidence in place, without leaving the list; the title opens the
        full finding. A finding that keeps recurring is one row (its occurrences are counted
        against the same fingerprint), so the length of the list is the number of distinct
        problems.
      </p>

      <h3>Severity</h3>
      <p>
        <code>critical</code> means someone should look today; <code>high</code>, this week.{" "}
        <code>medium</code> and <code>low</code> are worth a look when the first two are clear.
        Severity comes from the rule or check that raised the finding, not from a setting on
        this page.
      </p>

      <h3>Types</h3>
      <p>The type column uses plain labels. The ones you will see most:</p>
      <table>
        <thead>
          <tr>
            <th>Label</th>
            <th>Type</th>
            <th>What happened</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Guardrail catch</td><td><code>guardrail_detection</code></td><td>A detector matched something in a request, response, retrieved text or tool payload.</td></tr>
          <tr><td>Contained action</td><td><code>containment</code></td><td>A tool call was stopped or held by a permission, provenance or blast-radius rule, not by a content detector.</td></tr>
          <tr><td>Security test</td><td><code>redteam</code></td><td>Red-team probes got through without being blocked.</td></tr>
          <tr><td>Over-blocking</td><td><code>redteam_over_block</code></td><td>Benign control probes were refused.</td></tr>
          <tr><td>Unregistered agent</td><td><code>shadow_agent</code></td><td>Traffic from an agent nobody registered.</td></tr>
          <tr><td>No owner</td><td><code>unowned_agent</code></td><td>No one is accountable for the agent.</td></tr>
          <tr><td>Missed hand-off / Hand-off overdue</td><td><code>missed_escalation</code>, <code>handoff_sla_breach</code></td><td>A conversation should have gone to a person and did not, or did and nobody picked it up.</td></tr>
          <tr><td>Answered outside its boundary</td><td><code>boundary_breach</code></td><td>The agent answered beyond its declared knowledge boundary.</td></tr>
          <tr><td>Tool contract changed</td><td><code>mcp_schema_drift</code></td><td>An MCP tool&apos;s schema changed after approval.</td></tr>
        </tbody>
      </table>
      <p>
        The full list is in <Link href="/docs/reference/detectors">Detectors and findings</Link>.
      </p>

      <h3>Detection and containment; contained and would-have-been</h3>
      <p>
        A <strong>detection</strong> finding asks &quot;was the detector right?&quot;. A{" "}
        <strong>containment</strong> finding asks &quot;why did the agent try that?&quot;, and is
        named for what refused it, in one sentence: who tried to do what, with which data, and
        what happened. The end of the title says whether it took effect:
      </p>
      <ul>
        <li>
          <strong>(contained)</strong> or <strong>(held for approval)</strong>: the rule was
          enforcing and the call was stopped or sent to{" "}
          <Link href="/docs/app/approvals">Approvals</Link>.
        </li>
        <li>
          <strong>(would have been contained)</strong>, <strong>(would have been held for
          approval)</strong>, or a detection titled <strong>Would have been blocked on …</strong>:
          the rule is in observe mode. The call went through; the finding records what
          promoting the rule would change.
        </li>
      </ul>
      <Output title="agentfox findings --severity high (excerpt)">{` …ecxt83e6  high      containment          support-triage tried to redteam.sim.issue_refund outside
                                           the limits of its permission (contained)
 …ded9jv95  high      guardrail_detection  Would have been blocked on output: PII.CREDIT_CARD,
                                           PII.EMAIL, PII.US_SSN
 …4qk46y70  high 3x   containment          payments-ops tried to payments.transfer, which needs a
                                           person's sign-off first (would have been held for
                                           approval)`}</Output>

      <h2>The finding page</h2>
      <InTheApp path="/app/findings">Findings → a finding</InTheApp>
      <p>
        <code>/app/findings/&lt;id&gt;</code> loads <code>GET /api/findings/&#123;id&#125;</code>. The
        header gives the title, severity, type with its explanation, and when it was raised;
        below it, the status, the agent (linked), and the controls it maps to, each linking to
        the control on <Link href="/docs/app/compliance">Compliance</Link>.
      </p>

      <h3>What we found: the evidence panel</h3>
      <p>The evidence is drawn according to the type:</p>
      <ul>
        <li>
          <strong>Guardrail catch</strong>: the surface, the verdict, and a table of every match
          with entity, score, a masked excerpt and the OWASP and MITRE ATLAS references. Excerpts
          are masked when the detector runs; the underlying value is never stored. A link opens
          the trace with full detector activity.
        </li>
        <li>
          <strong>Security test</strong> and <strong>Over-blocking</strong>: the probes this
          finding is about first, each with the literal payload tried and the verdict; then the
          campaign it came from (probes run, attacks blocked, attacks that got through,
          legitimate requests blocked), and collapsed tables of results by category and every
          prompt tried.
        </li>
        <li>
          <strong>Everything else</strong>: the recorded evidence as labelled fields. For a
          containment finding that includes the tool, the rule, and where the arguments came
          from. To see the call itself, open the trace from the agent page or the Traces list.
        </li>
      </ul>
      <Output title="Evidence on a suppressed guardrail catch">{`surface  output   verdict  block
entity           score  masked excerpt          reference
PII.EMAIL        0.90   jane****************    LLM02  AML.T0057
PII.CREDIT_CARD  0.95   4111***************     LLM02  AML.T0057
PII.US_SSN       0.95   123-*******             LLM02  AML.T0057`}</Output>

      <h3>Resolve or suppress</h3>
      <p>An open finding has two actions, each with its own required text:</p>
      <ul>
        <li>
          <strong>Mark resolved</strong> — &quot;The underlying problem is actually fixed.&quot;
          Needs a note on what you did. The gateway refuses a resolve without one.
        </li>
        <li>
          <strong>Suppress</strong> — &quot;Not acting on it right now.&quot; Needs the reason
          you are accepting it. The finding stays visible under <code>status=suppressed</code>{" "}
          as a known, accepted issue rather than looking fixed.
        </li>
      </ul>
      <p>
        Both post the form to the web app, which sends{" "}
        <code>PATCH /api/findings/&#123;id&#125;</code> with <code>status</code> and{" "}
        <code>note</code> or <code>suppression_reason</code>. Afterwards the page shows who
        resolved or suppressed it and the text they gave. If the finding&apos;s own evidence
        still shows the problem (a posture score below 100%, or attacks that got through), the
        page warns you before you mark it resolved, and suggests Suppress instead.
      </p>
      <p>Over HTTP, with a token from <Link href="/docs/app/start#tokens">API tokens</Link>:</p>
      <Code>{`curl -s -X PATCH http://127.0.0.1:8080/api/findings/fnd_01m4699rz7ecxt83e6 \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN" -H 'Content-Type: application/json' \\
  -d '{"status":"resolved"}'`}</Code>
      <Output>{`{"detail":"resolving requires a note describing what was fixed"}`}</Output>
      <Callout kind="note">
        Suppressing a finding is not the same as suppressing a detector. A finding suppression
        only changes this record. To stop a detector acting on a known false positive, file
        feedback on the trace and create a scoped, expiring suppression on{" "}
        <Link href="/docs/app/policies#tuning">Guardrail tuning</Link>.
      </Callout>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "The same queue in a terminal, worst first", run: "agentfox findings" },
          { task: "Only critical", run: "agentfox findings --severity critical" },
          { task: "Full records for a script", run: "agentfox findings --json" },
          { task: "Open a finding by id", run: "⌘K, paste fnd_…" },
          { task: "Turn the would-have-been findings into real blocks", run: "agentfox policy enforce baseline", href: "/docs/app/policies" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>&quot;No findings match.&quot;</strong> Either nothing has tripped, or no
          traffic has been recorded; Start here says which.
        </li>
        <li>
          <strong>A resolved finding comes back.</strong> The same problem recurred and raised a
          new finding. Resolving records a fix; it does not silence the check.
        </li>
        <li>
          <strong>The type explanation says &quot;it changed the outcome&quot; on a
          would-have-been detection.</strong> Read the title: &quot;Would have been&quot; means
          observe mode, and the verdict shown in the evidence is the one the policy asked for.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>There is no bulk resolve or suppress, and no assignee field.</li>
        <li>
          There is no CLI command to resolve or suppress; use the page or{" "}
          <code>PATCH /api/findings/&#123;id&#125;</code>.
        </li>
        <li>Findings only exist for what passed through AgentFox.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/app/traces", label: "Traces", why: "the request behind a finding" },
          { href: "/docs/app/policies", label: "Policies and tuning", why: "promote a rule, or tune a noisy detector" },
          { href: "/docs/reference/detectors", label: "Detectors and findings", why: "every type and surface" },
        ]}
      />
    </article>
  );
}
