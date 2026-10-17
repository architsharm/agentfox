import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Traces",
  description:
    "The trace list and trace page: why it was blocked, spans, argument provenance, decisions, detector runs, the was-this-right feedback, and correlation with Langfuse and LangSmith.",
  path: "/docs/app/traces",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Traces</h1>
      <p className="docs-lede">
        A trace is one request taken apart: every check that ran on it, what each returned,
        where the values in its tool calls came from, and why it was blocked.
      </p>
      <InTheApp path="/app/traces">Traces</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>Someone asks why a response was blocked. Start from the trace, not the finding.</li>
        <li>A detector got it wrong, and you want to say so where it counts.</li>
        <li>To turn a real request into an eval case (copy its id to a suite).</li>
      </ul>

      <h2>The list</h2>
      <p>
        <code>/app/traces</code> loads <code>GET /api/traces?limit=150</code> with the filters
        in the URL: <strong>all</strong>, <strong>blocked</strong> (<code>verdict=block</code>),{" "}
        <strong>escalated</strong> (<code>verdict=escalate</code>), <strong>injection</strong>,{" "}
        <strong>PII</strong> and <strong>secrets</strong> (<code>entity_type=</code>), and an
        agent drop-down. Columns: trace id, agent, verdict, environment, model, intent, when.
        The caret expands a row to its decisions and detector runs without leaving the list.
      </p>
      <Output title="Traces list, page text, after agentfox demo">{`trace                  agent                 verdict  env         model   intent
trc_01m4699s1xf8phecv5 Support Triage Agent  block    production  echo-1  summarise the Q3 refunds document
trc_01m4699rvmjmf36y1c marketing-copy-bot    allow    production  echo-1  —
trc_01m4699rsf3he2g5ss Support Triage Agent  allow    production  echo-1  summarise the Q3 refunds document
trc_01m4699rrb1591azhg Support Triage Agent  allow    production  echo-1  answer a customer refund question`}</Output>

      <h2>The trace page</h2>
      <InTheApp path="/app/traces">Traces → a trace</InTheApp>
      <p>
        <code>/app/traces/&lt;id&gt;</code> loads <code>GET /api/traces/&#123;id&#125;</code>. The
        heading is the intent the caller sent, or the surfaces that were checked
        (&quot;Checked input and output&quot;), followed by the overall verdict. Then the agent,
        environment, time and trace id. In order down the page:
      </p>
      <table>
        <thead>
          <tr>
            <th>Panel</th>
            <th>What it shows</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Why — &lt;surface&gt;</strong></td>
            <td>
              One per decision that did not simply allow. The summary sentence; the rule&apos;s
              reason; <strong>Decided by</strong>: the detector, the entity, its offset and
              score, and the OWASP id; <strong>Also matched</strong>: other matches that did
              not decide it; <strong>What to do</strong>; and a <strong>Disagree?</strong> box
              to file a false positive. In observe mode it opens by saying nothing was stopped
              and this is what would have happened.
            </td>
          </tr>
          <tr>
            <td><strong>Span timeline</strong></td>
            <td>Each span with its kind, name and duration.</td>
          </tr>
          <tr>
            <td><strong>Argument provenance</strong></td>
            <td>
              Each tracked value (a JSON path), where it came from (user, retrieved, tool
              result…) and whether that source is trusted. This is what the taint rules read
              before an irreversible tool runs.
            </td>
          </tr>
          <tr>
            <td><strong>Decisions</strong></td>
            <td>
              Per surface: tool, verdict, mode, rules fired (id, effect, reason, controls) and
              latency.
            </td>
          </tr>
          <tr>
            <td><strong>Detector runs</strong></td>
            <td>
              Per detector and surface: status, score, time, the entities it found with a
              masked sample, and a <strong>was this right?</strong> control.
            </td>
          </tr>
        </tbody>
      </table>
      <Output title="Why panel, page text, on the demo's poisoned document">{`block on tool_result: INJECTION.INSTRUCTION_OVERRIDE matched at offset 59–91 with score 1.00,
which rule \`injection.indirect\` treats as block
Instruction-like content found in untrusted retrieved or tool content (indirect prompt injection).
Decided by    injection.heuristic found INJECTION.INSTRUCTION_OVERRIDE at offset 59–91 scoring 1.00 · LLM01
Also matched  INJECTION.COVERT_INSTRUCTION (1.00), INJECTION.ROLE_DELIMITER (0.70)
              Not what decided this one.
What to do
The instruction arrived in untrusted content. Fix the source, or lower the capability ceiling
for arguments derived from it rather than relaxing the detector.`}</Output>
      <p>
        A trace with no spans, decisions or detector runs is shown as{" "}
        <strong>nothing checked</strong>, not as allowed. That happens when a turn made no
        governed call, for example a tool-call integration on a turn where the model called no
        tool. An empty trace is not a pass.
      </p>

      <h2>Was this right? Feedback and what it feeds</h2>
      <p>
        On each detector run tied to a decision, pick <strong>correct — true positive</strong>,{" "}
        <strong>wrong — false positive</strong> or <strong>missed something</strong> and press{" "}
        <strong>file feedback</strong>. The <strong>File as a false positive</strong> button in
        a Why panel does the same with a note. Both send{" "}
        <code>POST /api/guardrails/feedback</code> with the decision, detector and entity, and
        return you to the trace with &quot;feedback recorded&quot;.
      </p>
      <ul>
        <li>
          One label per decision per person: labelling the same decision again replaces your
          earlier label.
        </li>
        <li>
          Feedback changes nothing on its own. It appears in the Feedback log on{" "}
          <Link href="/docs/app/policies#tuning">Guardrail tuning</Link>, where an open false
          positive is one click (<strong>suppress 30d</strong>) from a suppression scoped to
          that agent and entity.
        </li>
        <li>
          It feeds precision per detector and threshold recommendations. A detector needs at
          least five labelled verdicts before any recommendation is made.
        </li>
        <li>
          <Link href="/docs/reference/cli#cmd-policy-proposals-from-labels">agentfox policy proposals from-labels</Link>{" "}
          turns clean &quot;raise the threshold&quot; recommendations into change proposals for
          the rules involved, and applies nothing. With too few labels it files nothing:
        </li>
      </ul>
      <Code>{`agentfox policy proposals from-labels --days 30`}</Code>
      <Output>{`filed 0, refreshed 0, superseded 0`}</Output>

      <h2>Correlation with Langfuse and LangSmith</h2>
      <p>
        If your agent already sends traces to Langfuse, LangSmith or an OpenTelemetry backend,
        AgentFox stores the join key (a W3C <code>traceparent</code> or the vendor&apos;s trace
        header) when it records the decision. The web app does not show these links yet. Use
        the API:
      </p>
      <ul>
        <li>
          <code>GET /api/traces/&#123;id&#125;</code> returns a <code>links</code> list: system,
          external trace and run ids, project and URL.
        </li>
        <li>
          <code>GET /api/traces/resolve?system=langfuse&amp;external_id=…</code> goes the other
          way: from their trace or run id to the governed trace. <code>system</code> is{" "}
          <code>langsmith</code>, <code>langfuse</code> or <code>otel</code>.
        </li>
      </ul>
      <Code>{`curl -s "http://127.0.0.1:8080/api/traces/resolve?system=langfuse&external_id=abc123" \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN"`}</Code>
      <Output>{`{"detail":"no governed trace correlates with that id"}`}</Output>
      <p>
        Setting this up is in <Link href="/docs/guides/observability">Traces and integrations</Link>.
      </p>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "Open a trace by id", run: "⌘K, paste trc_…" },
          { task: "Every blocked request for one agent", run: "/app/traces?verdict=block&agent=support-triage" },
          { task: "Draft rule changes from your false-positive labels", run: "agentfox policy proposals from-labels --days 30" },
          { task: "Make a trace a regression case", run: "Evaluation → a suite → Promote a trace", href: "/docs/app/evals#cases" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>&quot;not tied to a decision&quot;</strong> in the feedback column. That
          detector run fed no decision, so there is nothing to label.
        </li>
        <li>
          <strong>The trace shows &quot;nothing checked&quot;.</strong> No governed step ran. Guard
          the prompt surface too, not only tool calls; see{" "}
          <Link href="/docs/guides/python-auto">One line in Python</Link>.
        </li>
        <li>
          <strong>Masked samples are unreadable.</strong> By design: samples are masked at
          capture and the original value is not stored anywhere to unmask.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>No CLI command lists or shows traces; use the page or <code>GET /api/traces</code>.</li>
        <li>The list shows the most recent 150 matching traces; there is no paging.</li>
        <li>External trace links are stored but not shown in the web app.</li>
      </ul>
      <Callout kind="tip">
        A trace is the right thing to link in an incident ticket: it carries the decisions,
        rules, versions and provenance that a finding summarises.
      </Callout>

      <NextSteps
        items={[
          { href: "/docs/app/policies#tuning", label: "Guardrail tuning", why: "where feedback lands" },
          { href: "/docs/app/findings", label: "Findings", why: "the queue built from these decisions" },
          { href: "/docs/guides/observability", label: "Traces and integrations", why: "OpenTelemetry, Langfuse, LangSmith" },
        ]}
      />
    </article>
  );
}
