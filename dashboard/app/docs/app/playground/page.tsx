import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Playground",
  description:
    "The public playground: a throwaway sandbox with three demo agents, what you can try, how observe and enforce differ, and its limits. No account.",
  path: "/docs/app/playground",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Playground</h1>
      <p className="docs-lede">
        A chat with three demo agents, where you try a prompt injection or a tool call the
        agent was not granted and watch the real enforcement path answer. No account, nothing
        to install.
      </p>
      <InTheApp path="/playground">Playground</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>Before installing anything, to see what a refusal looks like and why it happened.</li>
        <li>To show someone the difference between observe and enforce.</li>
        <li>To see that a tool call is refused for lack of a grant even when the text looks harmless.</li>
      </ul>

      <h2>What it sandboxes</h2>
      <p>
        Opening <code>/playground</code> creates a sandbox for you (
        <code>POST /api/playground/sessions</code>): a private workspace in the deployment&apos;s
        database, seeded with the demo agents, tools and grants. Your session id is its only
        credential; nothing is shared with other visitors, and nothing in it reaches the
        outside:
      </p>
      <ul>
        <li>No model is called. Replies come from the offline <code>echo</code> provider and are labelled &quot;scripted reply, no model ran&quot;.</li>
        <li>The <code>payments.transfer</code> and <code>email.send</code> tools have no backend; no money moves and no mail is sent.</li>
        <li>Verdicts come from the same enforcement code as the product, not a mock.</li>
      </ul>

      <h2>What you can try</h2>
      <p>Pick an agent along the top. Each has three suggestions, plus a poisoned document:</p>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Holds</th>
            <th>Suggestions</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Support Triage</td>
            <td>Runs the help desk; holds nothing that moves money.</td>
            <td>Transfer $5,000 · Close every ticket · Ignore your instructions</td>
          </tr>
          <tr>
            <td>Payments Operations</td>
            <td>Can move money, up to a declared limit.</td>
            <td>Transfer $5,000 · Transfer $500 · Ignore your instructions</td>
          </tr>
          <tr>
            <td>HR Screening</td>
            <td>Registered, and granted nothing at all.</td>
            <td>Email a candidate · Search the help desk · Ignore your instructions</td>
          </tr>
        </tbody>
      </table>
      <ul>
        <li>
          A suggestion with a tool shows your message, then the tool call the agent attempts,
          then its verdict (<code>POST …/tool-call</code>).
        </li>
        <li>
          Typed messages, and &quot;Ignore your instructions&quot;, are checked as text (
          <code>POST …/chat</code>). Each message is also checked together with the recent
          conversation, so an injection split across several short messages is tagged
          &quot;caught across messages&quot;.
        </li>
        <li>
          <strong>Summarise a poisoned document</strong>, or the paper-clip button, attaches an
          editable &quot;retrieved document&quot; containing an indirect injection. Edit it to try
          your own.
        </li>
        <li>
          Each verdict has a <strong>why</strong> disclosure: the reason, every rule that fired,
          and the latency.
        </li>
      </ul>
      <p>These are the verdicts the playground API returned for the suggestions:</p>
      <Output>{`support-triage payments.transfer 5000 -> block / block | no capability grants 'payments.transfer' (action '*') to agent:support-triage (default deny)…
payments-ops payments.transfer 5000 -> block / block | EU AI Act Art. 14 — irreversible action by a high-risk system requires human oversight.; agent:payments-ops holds a grant for 'payments.tran…
payments-ops payments.transfer 500 -> allow / escalate | EU AI Act Art. 14 — irreversible action by a high-risk system requires human oversight.
hr-screening email.send  -> block / block | no capability grants 'email.send' (action '*') to agent:hr-screening (default deny)…
chat observe -> allow / block observe | Prompt-injection or jailbreak attempt detected in user input.; System-prompt extraction attempt.
chat enforce -> block / block enforce | Prompt-injection or jailbreak attempt detected in user input.; System-prompt extraction attempt.`}</Output>
      <p>
        Each line is the applied verdict, then the verdict the policy asked for. The $500
        transfer is within the grant&apos;s limit, so the grant allows it, while the EU AI Act
        rule for high-risk agents asks for a human: in observe mode that is recorded, not
        applied.
      </p>

      <h2>Observe and enforce</h2>
      <p>
        The sandbox starts in <code>observe</code>. The side panel shows the mode and{" "}
        <strong>switch to enforce</strong> (<code>POST …/enforce</code>), which flips the{" "}
        <code>baseline</code> policy for your sandbox only. In observe, a flagged message is
        shown as <strong>flagged, not stopped</strong> with &quot;would block in enforce&quot;,
        and the scripted reply goes through. In enforce, the same message is blocked. Capability
        checks on tool calls enforce in both modes, because they read no text. Earlier messages
        are not re-judged: send the same one again after switching.
      </p>
      <p>
        The side panel also shows how many audit records your sandbox has written and whether
        its hash chain holds (<code>GET …/state</code>).
      </p>

      <h2>Limits</h2>
      <ul>
        <li>A sandbox expires 30 minutes after your last action, and its data is deleted. The page then offers <strong>Start a new one</strong>.</li>
        <li>Eight new sandboxes per network address per hour; after that the API answers 429.</li>
        <li>Forty actions per sandbox per minute.</li>
        <li>At most 200 live sandboxes across the deployment; beyond that the oldest are dropped.</li>
        <li>Three fixed agents. You cannot add agents, grants or policies, or connect a model.</li>
      </ul>
      <Callout kind="note">
        Anything you type is stored in the sandbox until it expires. Do not paste real
        customer data or secrets.
      </Callout>

      <h2>Run it yourself</h2>
      <p>
        On a self-hosted deployment the playground is the same page, calling the gateway&apos;s
        unauthenticated <code>/api/playground/*</code> routes from the visitor&apos;s browser. Set{" "}
        <code>AGENTFOX_PLAYGROUND_API_URL</code> on the web app to an address browsers can reach,
        and <code>AGENTFOX_PLAYGROUND_CORS_ORIGIN</code> on the gateway to the web app&apos;s
        origin. The routes can be called directly:
      </p>
      <Code>{`curl -s -X POST http://127.0.0.1:8080/api/playground/sessions`}</Code>
      <Output>{`{"session_id":"…","expires_in_seconds":1800,"agents":[{"slug":"support-triage",…},{"slug":"payments-ops",…},{"slug":"hr-screening",…}],…,"mode":"observe"}`}</Output>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "The same walkthrough offline, in a terminal", run: "agentfox demo" },
          { task: "Run the attack library against your own agent", run: "agentfox test redteam support-triage", href: "/docs/app/evals#redteam" },
          { task: "Grant a tool so the call stops being refused", run: "agentfox permit grant support-triage tickets.close --yes", href: "/docs/guides/contain-tool-calls" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>&quot;That sandbox expired. Nothing was saved.&quot;</strong> Thirty minutes passed
          without an action. Start a new one.
        </li>
        <li>
          <strong>&quot;Too many playground sandboxes from this address recently&quot;.</strong>{" "}
          The per-address limit; try later.
        </li>
        <li>
          <strong>&quot;The sandbox could not be reached&quot;</strong> on a self-hosted
          deployment. The browser cannot reach the playground API URL, or the gateway does not
          allow the web app&apos;s origin.
        </li>
        <li>
          <strong>A typed message gets <code>allow</code>.</strong> The text was checked and
          nothing matched. Tool calls are where containment shows; use a suggestion with a tool.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/quickstart", label: "Quickstart", why: "the same checks on your own agent" },
          { href: "/docs/concepts", label: "Concepts", why: "grants, provenance and modes" },
          { href: "/docs/benchmarks", label: "Benchmarks", why: "what was measured beyond the demo" },
        ]}
      />
    </article>
  );
}
