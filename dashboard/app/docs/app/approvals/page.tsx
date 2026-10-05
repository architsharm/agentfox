import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Approvals and escalation",
  description:
    "Deciding held tool calls, the hand-off queue and its SLA, missed escalations, conversation transcripts, and the escalation policy.",
  path: "/docs/app/approvals",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Approvals and escalation</h1>
      <p className="docs-lede">
        Two queues that need a person: the Approvals tab holds single tool calls waiting for
        sign-off; the Escalation tab holds whole conversations that should have gone to a
        human.
      </p>
      <InTheApp path="/app/approvals">Approvals</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>An agent&apos;s call is held and the agent is waiting on your answer.</li>
        <li>A customer asked for a person, and you need to see whether anyone picked it up.</li>
        <li>To tune what counts as &quot;should have escalated&quot;.</li>
      </ul>

      <h2>Approvals tab</h2>
      <p>
        <code>/app/approvals</code>, filtered by <code>?status=</code>: <strong>pending</strong>{" "}
        (the default), <strong>approved</strong>, <strong>denied</strong>,{" "}
        <strong>expired</strong>, each with its count. From{" "}
        <code>GET /api/approvals?status=…</code>.
      </p>
      <p>
        A call lands here when the capability grant behind it was made with{" "}
        <code>--requires-approval</code>, or when a rule escalates instead of blocking: most
        often an irreversible tool called with arguments that came from something untrusted,
        or an irreversible action by a high-risk agent. Each row shows:
      </p>
      <ul>
        <li><strong>agent</strong> and <strong>tool</strong></li>
        <li>
          <strong>reason</strong>: every rule that fired, one per line. This is what you are
          deciding against.
        </li>
        <li><strong>arguments</strong>: the exact values the call would run with</li>
        <li><strong>requested</strong> and <strong>expires</strong> (a countdown)</li>
        <li>
          <strong>Approve</strong> with an optional rationale, or <strong>Deny</strong>. Deny means
          the call does not run, the same outcome as a block.
        </li>
      </ul>
      <Output title="A pending approval, page text">{`agent                      tool               reason
Payments Operations Agent  payments.transfer  EU AI Act Art. 14 — irreversible action by a high-risk system requires human oversight.
                                              Irreversible tool invoked with arguments originating in untrusted content (retrieved
                                              document, tool result or sub-agent output). Human approval required.
                                              The granting capability requires human approval for this action.
arguments: amount 250 · currency USD · to acct_attacker_991`}</Output>
      <p>
        The buttons call <code>POST /api/approvals/&#123;id&#125;/approve</code> and{" "}
        <code>/deny</code> with <code>&#123;&quot;rationale&quot;: &quot;…&quot;&#125;</code>. Deciding needs owner,
        admin or security, and each decision is written to the audit chain as{" "}
        <code>approval.approved</code> or <code>approval.denied</code> with the rationale.
      </p>
      <p>
        An unanswered request is denied when it expires, and the call stays blocked: it fails
        closed. The SDK waiting on an approval polls{" "}
        <code>GET /api/approvals/&#123;id&#125;</code>. There is no CLI command for deciding
        approvals; over HTTP:
      </p>
      <Code>{`curl -s -X POST http://127.0.0.1:8080/api/approvals/apr_01m4699s09007f7x9p/deny \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN" -H 'Content-Type: application/json' \\
  -d '{"rationale":"account closure needs a ticket"}'`}</Code>
      <Output>{`{"id":"apr_01m4699s09007f7x9p","status":"denied","resolver":"admin@example.com"}`}</Output>
      <p>
        An empty pending queue says &quot;Nothing is waiting on you&quot;, links to what has
        already been answered, and to the agents and rules that would put something here.
      </p>

      <h2 id="escalation">Escalation tab</h2>
      <InTheApp path="/app/approvals?tab=escalation">Approvals → Escalation</InTheApp>
      <p>
        <code>/app/approvals?tab=escalation</code>, filterable by agent. Built from{" "}
        <code>GET /api/escalation/report</code>, <code>/missed</code>, <code>/handoffs</code> and{" "}
        <code>/policy</code>. The strip at the top: missed-escalation rate (red above 5%),
        conversations that qualified for a hand-off, hand-offs past their SLA, hand-offs
        missing context, and false resolutions.
      </p>

      <h3>Hand-off queue</h3>
      <p>Each row is a conversation an agent handed to a person:</p>
      <ul>
        <li>
          <strong>conversation</strong>: the summary, its session id, a <code>sample data</code>{" "}
          tag for seeded ones, and a link to the trace if there is one. The summary opens the
          transcript.
        </li>
        <li>
          <strong>status</strong>: <code>pending</code>, <code>acknowledged</code>,{" "}
          <code>breached</code> (past its SLA) or <code>resolved</code>; a{" "}
          <code>retroactive</code> tag when it was raised by the after-the-fact scan.
        </li>
        <li><strong>owner</strong>: the role it is routed to</li>
        <li>
          <strong>context</strong>: how complete the hand-off is: the original request, a
          summary, what was tried, why it was blocked, and a customer reference. Anything
          missing is listed. A hand-off a person has to re-interview the customer for has
          failed even though it happened.
        </li>
        <li><strong>due</strong> and <strong>reason</strong></li>
        <li>
          <strong>acknowledge</strong> on pending rows (
          <code>POST /api/escalation/handoffs/&#123;id&#125;/acknowledge</code>). A hand-off past
          its SLA becomes <code>breached</code> and appears in the attention queue as high.
        </li>
      </ul>

      <h3>Missed escalations</h3>
      <p>
        Conversations that met an escalation condition and never got a person, found after
        the fact by replaying them against the policy. At runtime there is nothing to see: the
        failure is the absence of an event. Each row has the turn count, the turn it
        qualified at, and the first two triggers.
      </p>

      <h3>Conversation transcript</h3>
      <p>
        <code>/app/escalation/conversations/&lt;session id&gt;</code> (
        <code>GET /api/escalation/conversations/&#123;id&#125;</code>) replays every turn against
        the policy. Cards say whether it qualified, whether it actually escalated, the turn
        count, and depth against the turn-depth limit. A red note appears when it qualified
        and no hand-off was raised. The transcript shows user and agent text per turn, tags
        for &quot;claims resolved&quot; and &quot;escalated here&quot;, a trace link, and the
        triggers on each turn.
      </p>
      <Output title="Transcript, page text (seeded conversation)">{`#  user                                                         agent                                  triggers
2  I want a refund reversed and I want to speak to a manager.  I'm connecting you with a member of    high explicit_request
                                                               our team who can take this further.   the user asked for a human
                                                               escalated here`}</Output>

      <h3>Escalation policy</h3>
      <p>
        Collapsed at the foot of the tab: <strong>Owner role</strong> (default{" "}
        <code>support</code>), <strong>SLA (minutes)</strong> (default 60),{" "}
        <strong>Mode</strong> (observe or enforce), and <strong>Conditions</strong> as JSON:{" "}
        <code>explicit_request</code>, <code>repeated_failure</code>,{" "}
        <code>repeated_abstention</code>, <code>turn_depth</code>, <code>sentiment_below</code>,{" "}
        <code>regulated_topics</code>, <code>confidence_below</code>. Fields you leave out fall
        back to the platform default. Saving sends <code>PUT /api/escalation/policy</code>.
        This edits the org default; per-agent policies exist in the API (
        <code>?agent=</code>) and the CLI, not here.
      </p>
      <Code lang="json" title="the default conditions">{`{
  "explicit_request": true,
  "repeated_failure": 2,
  "repeated_abstention": 2,
  "turn_depth": 8,
  "sentiment_below": -0.6,
  "regulated_topics": ["legal", "medical", "financial_advice", "complaint", "discrimination"],
  "confidence_below": 0.35
}`}</Code>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "Scan recent conversations for missed escalations", run: "agentfox report escalations --hours 24" },
          { task: "Raise hand-offs for the ones it finds", run: "agentfox report escalations --hours 24 --apply" },
          { task: "Set a per-agent escalation policy", run: "agentfox declare escalation --agent support-triage --turn-depth 6 --sla-minutes 30" },
          { task: "Require sign-off for a tool", run: "agentfox permit grant payments-ops payments.transfer --requires-approval --yes", href: "/docs/guides/approvals" },
        ]}
      />
      <Output title="agentfox report escalations --hours 24">{`1 conversation(s) · 1 qualified for escalation · 0 missed (0.0%, target < 5%)`}</Output>

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>Approve returns an error banner.</strong> Deciding needs owner, admin or
          security.
        </li>
        <li>
          <strong>An approval expired before anyone saw it.</strong> It was denied and the call
          blocked. Shorten the path to whoever decides, or narrow the grant so fewer calls need
          sign-off.
        </li>
        <li>
          <strong>&quot;conditions must be valid JSON&quot;</strong> on Save escalation policy:
          the JSON did not parse; nothing was saved.
        </li>
        <li>
          <strong>Missed escalations is empty.</strong> Either escalation works, or no
          conversation turns were recorded for the window.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>No CLI command to decide an approval; use the page or the HTTP routes.</li>
        <li>No reassignment of hand-offs and no resolve button; acknowledge is the only action.</li>
        <li>Escalation conditions are signals, not guarantees, which is why the policy ships in observe.</li>
      </ul>
      <Callout kind="note">
        Approvals is the human half of containment. Which calls end up here is decided by
        grants and rules; see <Link href="/docs/guides/approvals">Approvals and the kill switch</Link>.
      </Callout>

      <NextSteps
        items={[
          { href: "/docs/guides/approvals", label: "Approvals and the kill switch", why: "set up sign-off from code" },
          { href: "/docs/app/agents#kill-switch", label: "Kill switch", why: "stop an agent outright" },
          { href: "/docs/app/findings", label: "Findings", why: "breached hand-offs also land there" },
        ]}
      />
    </article>
  );
}
