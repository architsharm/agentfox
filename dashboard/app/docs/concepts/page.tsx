import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { Callout, Code, NextSteps, Output } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Concepts",
  description:
    "Agents, tools, impact, grants, provenance, policies, verdicts, findings, approvals, proposals, control points and the audit chain.",
  path: "/docs/concepts",
});

function Def({ id, term, children }: { id: string; term: string; children: ReactNode }) {
  return (
    <section id={id}>
      <h2>{term}</h2>
      {children}
    </section>
  );
}

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>Concepts</h1>
      <p className="docs-lede">
        The vocabulary every other page uses, defined precisely enough to predict what
        AgentFox will decide.
      </p>

      <h2>When to use this</h2>
      <p>
        Read it once after the <Link href="/docs/quickstart">Quickstart</Link>, and come
        back when a verdict surprises you. Each term says where it is used, so you can jump
        to the guide or command that works with it.
      </p>
      <nav aria-label="On this page">
        <p>
          <a href="#agent">Agent</a> · <a href="#tool">Tool</a> · <a href="#impact">Impact</a> ·{" "}
          <a href="#grant">Capability grant</a> · <a href="#provenance">Provenance</a> ·{" "}
          <a href="#output-trust">Output trust</a> · <a href="#policy">Policy, pack, rule, mode</a> ·{" "}
          <a href="#verdict">Verdict</a> · <a href="#decision">Decision and trace</a> ·{" "}
          <a href="#findings">Finding</a> · <a href="#approval">Approval</a> ·{" "}
          <a href="#proposal">Proposal</a> · <a href="#control-points">Control points</a> ·{" "}
          <a href="#evidence">Audit chain and evidence</a>
        </p>
      </nav>

      <h2>How a tool call is decided</h2>
      <p>
        Most of the concepts below meet in one place: the check that runs before a tool call
        executes. In order:
      </p>
      <ol>
        <li>
          Which <a href="#agent">agent</a> is calling, and is it stopped (quarantine or kill
          switch)?
        </li>
        <li>
          Does it hold a <a href="#grant">grant</a> for this <a href="#tool">tool</a>, and do
          the argument values fit the grant&apos;s limits? No grant: refused (default deny).
        </li>
        <li>
          What is the tool&apos;s <a href="#impact">impact</a>, and what is the{" "}
          <a href="#provenance">provenance</a> of the arguments? Untrusted values in an
          irreversible call: escalated to a person.
        </li>
        <li>
          Was a value produced by one tool passed into a higher-impact one (composition)?
          Was a task <a href="#policy">intent</a> declared? Is the run looping or over budget?
        </li>
        <li>
          What did the detectors find in the arguments? Detection rules apply on top, in
          whatever <a href="#policy">mode</a> their policy is in.
        </li>
      </ol>
      <p>
        The strongest effect wins, it becomes the <a href="#verdict">verdict</a>, and the{" "}
        <a href="#decision">decision</a> is written to the <a href="#evidence">audit chain</a>.
        Steps 2 and 3 read no text at all, which is why they hold when a detector misses.
      </p>

      <Def id="agent" term="Agent">
        <p>
          A program that calls a model and can take actions. AgentFox identifies each one by
          a slug such as <code>support-triage</code> or <code>payments-ops</code>. Every
          grant, policy binding, finding and decision is attached to an agent.
        </p>
        <table>
          <tbody>
            <tr>
              <th>Registered</th>
              <td>
                Created by <code>agentfox.auto(&quot;support-triage&quot;)</code>, by the hooks
                installer, or in the web app, with an owner and a risk tier.
              </td>
            </tr>
            <tr>
              <th>Shadow</th>
              <td>
                Registered by its own traffic: the first call through the gateway from an
                unknown agent creates it, unowned. It shows up in{" "}
                <code>agentfox agents list</code> and as a <code>shadow_agent</code> finding.
              </td>
            </tr>
            <tr>
              <th>Stopped</th>
              <td>
                <code>agentfox agents quarantine</code> or <code>agentfox agents kill</code>;
                every call is refused until <code>agentfox agents resume</code>.
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          Used in: <Link href="/docs/app/agents">Agents in the web app</Link>,{" "}
          <Link href="/docs/guides/approvals">Approvals and the kill switch</Link>.
        </p>
      </Def>

      <Def id="tool" term="Tool">
        <p>
          Anything an agent can call that is not the model: a Python function, an HTTP API,
          an MCP server method, a shell. A tool has a key (<code>tickets.close</code>,{" "}
          <code>crm_lookup</code>, <code>billing.export</code>), an <a href="#impact">impact</a>,
          an <a href="#output-trust">output trust</a>, and optionally the downstream effects it
          triggers. Tool declarations are organisation-wide.
        </p>
        <p>
          Used in: <code>agentfox declare tool</code>, <code>agentfox declare list tools</code>,{" "}
          <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>.
        </p>
      </Def>

      <Def id="impact" term="Impact">
        <p>
          What a tool can do to the world. It is the axis every containment rule reasons
          over. Four tiers:
        </p>
        <table>
          <thead>
            <tr>
              <th>Impact</th>
              <th>Meaning</th>
              <th>With untrusted arguments</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>read</code></td>
              <td>Reads data, changes nothing.</td>
              <td>Allowed, if granted.</td>
            </tr>
            <tr>
              <td><code>write</code></td>
              <td>Changes data, and the change can be undone.</td>
              <td>Escalated when an argument came from a tool result or worse.</td>
            </tr>
            <tr>
              <td><code>high_impact</code></td>
              <td>Reversible, but costly if wrong.</td>
              <td>Escalated when anything is untrusted.</td>
            </tr>
            <tr>
              <td><code>irreversible</code></td>
              <td>Cannot be taken back: sending, paying, deleting.</td>
              <td>
                Escalated when anything is untrusted; also escalated when no task intent was
                declared.
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          <b>Inferred or declared.</b> A tool <code>agentfox.auto()</code> sees for the first
          time is registered with an impact guessed from its name, and marked{" "}
          <code>inferred</code> until you confirm it:
        </p>
        <Code>{`agentfox declare list tools
agentfox declare tool email_send --impact irreversible`}</Code>
        <Output>{`  tool             impact                                                    output       triggers
  crm_lookup       read (inferred — confirm with \`agentfox declare tool\`)    untrusted    —
  email_send       irreversible (inferred — confirm with \`agentfox           untrusted    —
                   declare tool\`)
…
email_send declared — impact irreversible, output untrusted
  arguments carrying untrusted provenance now require approval or are refused, whether or not a
detector fires`}</Output>
        <Callout kind="warning" title="A floor, not a fact">
          The tier is only as good as the declaration. A destructive tool declared{" "}
          <code>read</code> is treated as read everywhere downstream, and a shell tool has
          one tier for both <code>ls</code> and <code>rm -rf</code>. See{" "}
          <Link href="/docs/limits">Limits</Link>.
        </Callout>
      </Def>

      <Def id="grant" term="Capability grant">
        <p>
          Permission for one agent to call one tool (or a glob such as{" "}
          <code>tickets.*</code>), with conditions. Default is deny: once an agent is under
          containment, a call no grant covers is refused with <code>capability.denied</code>,
          whether or not anything looked suspicious.
        </p>
        <table>
          <thead>
            <tr>
              <th>Part</th>
              <th>Flag</th>
              <th>What it does</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Argument limits</td>
              <td><code>--limit rows:lt=1000</code>, <code>--limit currency:in=USD,EUR</code></td>
              <td>A call outside a limit is refused with <code>capability.constraint_violated</code>.</td>
            </tr>
            <tr>
              <td>Provenance ceiling</td>
              <td><code>--max-taint user</code> (default)</td>
              <td>
                The worst <a href="#provenance">provenance</a> an argument may carry and still
                go through without an approval.
              </td>
            </tr>
            <tr>
              <td>Approval</td>
              <td><code>--requires-approval</code></td>
              <td>Every matching call goes to a person first.</td>
            </tr>
            <tr>
              <td>Expiry</td>
              <td><code>--expires-in-days 30</code></td>
              <td>The grant withdraws itself.</td>
            </tr>
            <tr>
              <td>Accountability</td>
              <td><code>--granted-by</code></td>
              <td>Recorded in the audit chain with the grant.</td>
            </tr>
          </tbody>
        </table>
        <p>
          The same <code>billing.export</code> call, against a grant of{" "}
          <code>--limit rows:lt=1000 --max-taint user</code>, asked three ways through{" "}
          <code>POST /v1/guard/tool_call</code>:
        </p>
        <table>
          <thead>
            <tr>
              <th>Arguments</th>
              <th>Provenance</th>
              <th>Verdict</th>
              <th>Rules fired</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>rows: 250</code></td>
              <td>all <code>user</code></td>
              <td><code>allow</code></td>
              <td>none</td>
            </tr>
            <tr>
              <td><code>rows: 250</code></td>
              <td><code>to</code> from <code>tool_result</code></td>
              <td><code>escalate</code>, with an <code>approval_id</code></td>
              <td><code>taint.irreversible_tool</code>, <code>capability.approval_required</code></td>
            </tr>
            <tr>
              <td><code>rows: 5000</code></td>
              <td>all <code>user</code></td>
              <td><code>block</code></td>
              <td><code>capability.constraint_violated</code></td>
            </tr>
          </tbody>
        </table>
        <p>
          The middle row is the point: same tool, same values, same agent; only where one
          value came from differs. Grants are made by hand with{" "}
          <code>agentfox permit grant</code> (it asks before it writes; <code>--yes</code> in
          scripts) or drafted from traffic as <a href="#proposal">proposals</a>.
        </p>
        <p>
          Used in: <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>,{" "}
          <Link href="/docs/guides/gateway">the gateway</Link>.
        </p>
      </Def>

      <Def id="provenance" term="Provenance (taint)">
        <p>
          Where an argument&apos;s value came from. AgentFox tracks it per value and compares
          it against the grant&apos;s ceiling and the tool&apos;s impact. Ordered from most to
          least trusted:
        </p>
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>Means</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>none</code></td>
              <td>No external origin.</td>
            </tr>
            <tr>
              <td><code>user</code></td>
              <td>A person typed it: the user&apos;s message.</td>
            </tr>
            <tr>
              <td><code>retrieved</code></td>
              <td>It came out of a retrieved document.</td>
            </tr>
            <tr>
              <td><code>tool_result</code></td>
              <td>It came out of another tool&apos;s output, such as a fetched web page.</td>
            </tr>
            <tr>
              <td><code>subagent</code></td>
              <td>Another agent produced it.</td>
            </tr>
            <tr>
              <td><code>memory</code></td>
              <td>It was read back from the agent&apos;s long-term memory.</td>
            </tr>
          </tbody>
        </table>
        <p>
          Everything after <code>user</code> is untrusted. With <code>agentfox.auto()</code>,
          provenance is read from the conversation: a value copied out of a{" "}
          <code>role=&quot;tool&quot;</code> message counts as tool output. Over HTTP, the caller
          says it in the request&apos;s <code>provenance</code> map.
        </p>
        <h3 id="taint-scope">Session or argument scope</h3>
        <p>
          One setting, <code>taint_scope</code>, decides what a call&apos;s provenance is:
        </p>
        <table>
          <thead>
            <tr>
              <th><code>taint_scope</code></th>
              <th>A call&apos;s provenance is</th>
              <th>Trade-off</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>session</code> (default)</td>
              <td>
                The worst untrusted content anywhere in the run so far, or in the call&apos;s
                own arguments. Once the agent has read a web page, every later irreversible
                call carries it.
              </td>
              <td>
                Contains attacks whose payload never lands in an argument. Escalates much
                legitimate work.
              </td>
            </tr>
            <tr>
              <td><code>argument</code></td>
              <td>Only what this call&apos;s own arguments were copied from.</td>
              <td>
                Lets more legitimate work through. Misses an attack whose values are not
                found in the arguments: identifiers shorter than six characters are never
                matched, nor is attacker text inside a longer argument.
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          Measured on AgentDojo (97 user tasks, 949 attack pairs, provenance inferred from the
          real tool outputs, every detector off), from{" "}
          <code>benchmarks/agentdojo/README.md</code>:
        </p>
        <table>
          <thead>
            <tr>
              <th>Provenance</th>
              <th>Benign tasks run without escalation</th>
              <th>Attack pairs contained</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Session-level (shipped default)</td>
              <td>24/97 (24.7% [17.2, 34.2])</td>
              <td>588/588</td>
            </tr>
            <tr>
              <td>Argument-level</td>
              <td>37/97 (38.1% [29.1, 48.1])</td>
              <td>527/588</td>
            </tr>
            <tr>
              <td>Session-level, read-only tools exempt</td>
              <td>43/97</td>
              <td>588/588</td>
            </tr>
            <tr>
              <td>Argument-level, read-only tools exempt</td>
              <td>62/97 (63.9% [54.0, 72.8])</td>
              <td>527/588</td>
            </tr>
          </tbody>
        </table>
        <p>
          The <Link href="/docs/quickstart">Quickstart</Link> shows the same trade on four
          tickets. Under <code>session</code>, two legitimate replies sent after the agent read
          a status page were escalated, and the injected email was refused. With{" "}
          <code>AGENTFOX_TAINT_SCOPE=argument</code>, the same run gave:
        </p>
        <Output>{`Ticket T-311 from customer c -> T-311 handled.
Ticket T-312 from customer c -> T-312 handled.
Ticket T-313 from customer c -> T-313 handled.
Ticket T-314 from customer c -> refused: agentfox: tool call email_send was refused by composition.escalation: argument 'to' carries a value produced by tool 'web_fetch' (read), now passed into 'email_send' (irreversible) — …`}</Output>
        <p>
          Set it in <code>agentfox.toml</code> or the environment (
          <Link href="/docs/reference/config#policy">Configuration</Link>). A value other than{" "}
          <code>session</code> or <code>argument</code> is an error at startup, not a silent
          fallback.
        </p>
      </Def>

      <Def id="output-trust" term="Output trust">
        <p>
          Whether values copied out of a tool&apos;s output count as untrusted. Every tool is{" "}
          <code>untrusted</code> unless declared otherwise. Declare <code>trusted</code> only for
          a system of record you control: a CRM read, your own mail service&apos;s
          confirmation. Then an email address copied out of the CRM into{" "}
          <code>email_send</code> is not treated like one scraped from a web page, and the
          tool no longer raises the run&apos;s provenance.
        </p>
        <Code>{`agentfox declare tool crm_lookup --impact read --output-trust trusted`}</Code>
        <Output>{`crm_lookup declared — impact read, output trusted
  values an agent copies out of this tool's output no longer count as untrusted input, and no longer
raise the run's provenance`}</Output>
        <p>
          This is also the fix for <code>composition.escalation</code>, which refuses a value
          produced by one tool and passed into a higher-impact one, unless the producing tool
          is trusted.
        </p>
      </Def>

      <Def id="policy" term="Policy, pack, rule and mode">
        <table>
          <tbody>
            <tr>
              <th>Rule</th>
              <td>
                A condition and an effect: <code>taint.irreversible_tool</code> says an
                irreversible tool with arguments above <code>user</code> escalates. Each rule
                maps to controls in the catalog.
              </td>
            </tr>
            <tr>
              <th>Policy</th>
              <td>A named, versioned set of rules, bound to agents, teams or environments.</td>
            </tr>
            <tr>
              <th>Pack</th>
              <td>
                A policy shipped with the product. <code>baseline</code> (detector rules),{" "}
                <code>eu-ai-act-high-risk</code>, <code>tool-containment</code> (grants,
                provenance, composition, intent, loops, budgets), and{" "}
                <code>coding-agent</code>, which is only bound to agents that coding-agent hooks
                govern.
              </td>
            </tr>
            <tr>
              <th>Mode</th>
              <td>
                <b>observe</b> records what the policy would have done and changes nothing;{" "}
                <b>enforce</b> does it. The mode belongs to the policy, not to the
                integration.
              </td>
            </tr>
          </tbody>
        </table>
        <Code>{`agentfox policy list`}</Code>
        <Output>{`policy               version  mode     rules
baseline             v1       observe  13
eu-ai-act-high-risk  v1       observe  7
tool-containment     v1       enforce  25`}</Output>
        <p>
          <code>tool-containment</code> enforces from <code>agentfox init</code> because its
          rules are structural facts (no grant, an untrusted value in an irreversible call),
          not classifier scores. The detector packs start in observe because a false block
          is how guardrails get switched off. <code>agentfox policy enforce baseline</code>{" "}
          is the one step that starts blocking model traffic, and{" "}
          <code>agentfox policy observe baseline</code> reverses it.
        </p>
        <p>
          <b>Intent</b> is the agent&apos;s task in a sentence, declared with{" "}
          <code>auto(intent=…)</code> or the <code>X-Nometria-Intent</code> header. An
          irreversible call with no declared intent is escalated by{" "}
          <code>intent.undeclared_irreversible</code>.
        </p>
        <p>
          The integration has its own <code>mode</code> too, for{" "}
          <code>agentfox.auto()</code>: <code>&quot;policy&quot;</code> (default) raises
          exactly when an enforcing policy refuses; <code>&quot;observe&quot;</code> never
          raises; <code>&quot;enforce&quot;</code> raises whenever the effective verdict
          blocks, even for a policy in observe, for tests and CI.
        </p>
        <p>
          Used in: <Link href="/docs/reference/policies">Policy language</Link>,{" "}
          <Link href="/docs/app/policies">Policies in the web app</Link>,{" "}
          <Link href="/docs/guides/tuning">Tune detectors</Link>.
        </p>
      </Def>

      <Def id="verdict" term="Verdict">
        <p>
          What a check returns. Every rule that fires has an effect; the strongest one wins.
          From weakest to strongest:
        </p>
        <table>
          <thead>
            <tr>
              <th>Effect</th>
              <th>What happens</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>allow</code></td>
              <td>The call or text goes through.</td>
            </tr>
            <tr>
              <td><code>tokenize</code>, <code>mask</code>, <code>redact</code></td>
              <td>It goes through with the matched values replaced.</td>
            </tr>
            <tr>
              <td><code>abstain</code></td>
              <td>The answer is withheld and a declared refusal is said instead.</td>
            </tr>
            <tr>
              <td><code>escalate</code></td>
              <td>Held for a person; an <a href="#approval">approval</a> is created.</td>
            </tr>
            <tr>
              <td><code>block</code></td>
              <td>Refused.</td>
            </tr>
          </tbody>
        </table>
        <p>
          Over HTTP the response is a 200 carrying the verdict, so your code branches on{" "}
          <code>verdict</code> rather than on an error status. In Python, an enforced{" "}
          <code>block</code> or <code>escalate</code> on a tool call raises{" "}
          <code>agentfox.Blocked</code>. In observe mode two verdicts are recorded: the one
          applied, and the one the policy would have applied (
          <code>x-nometria-verdict</code> and <code>x-nometria-effective-verdict</code> on a
          proxied call). The gap between them is what you watch before enforcing.
        </p>
      </Def>

      <Def id="decision" term="Decision and trace">
        <p>
          A <b>decision</b> is one evaluation: the surface checked, the verdict, every rule
          that fired with its reason, the detector results, and the provenance it was
          judged on. It has an id (<code>dec_…</code>) and lands in the audit chain.
        </p>
        <p>
          A <b>trace</b> (<code>trc_…</code>) is one request end to end: the input guard, the
          model call, the output guard, each tool call, with timings. The decisions hang off
          it. <code>agentfox.auto()</code> creates one per model call; the gateway returns its
          id in <code>x-nometria-trace</code>.
        </p>
        <p>
          Checks run on nine surfaces: <code>input</code>, <code>output</code>,{" "}
          <code>tool_args</code>, <code>tool_result</code>, <code>retrieved</code>,{" "}
          <code>memory_write</code>, <code>agent_message</code>, <code>completion</code> (the
          agent claiming it is finished) and <code>reasoning</code>.
        </p>
        <p>
          Used in: <Link href="/docs/app/traces">Traces in the web app</Link>,{" "}
          <Link href="/docs/guides/observability">Traces and integrations</Link>.
        </p>
      </Def>

      <Def id="findings" term="Finding">
        <p>
          Something a person should look at. Findings are deduplicated by fingerprint, so a
          problem that recurs is one finding with a count (<code>4x</code>), not four.
        </p>
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Raised when</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>containment</code></td>
              <td>
                A permission, provenance, composition or blast-radius rule stopped (or would
                have stopped) a tool call. Titled by what stopped it, for example &quot;tried
                to pass the output of web_fetch into email_send, a higher-impact action&quot;.
              </td>
            </tr>
            <tr>
              <td><code>guardrail_detection</code></td>
              <td>A detector matched (injection, personal data, a secret) and a rule acted on it.</td>
            </tr>
            <tr>
              <td><code>shadow_agent</code>, unowned or stale agents</td>
              <td>Inventory problems from traffic and the registry.</td>
            </tr>
          </tbody>
        </table>
        <p>
          <b>Contained or would have been.</b> A finding ending <em>(contained)</em> or{" "}
          <em>(held for approval)</em> was stopped by an enforcing rule. One ending{" "}
          <em>(would have been contained)</em> was decided by a rule in observe mode and let
          through. <code>agentfox report</code> keeps the two in separate sections.
        </p>
        <p>
          Used in: <code>agentfox findings</code>,{" "}
          <Link href="/docs/app/findings">Findings in the web app</Link>,{" "}
          <Link href="/docs/reference/detectors">Detectors and findings</Link>.
        </p>
      </Def>

      <Def id="approval" term="Approval">
        <p>
          The record an <code>escalate</code> verdict creates (<code>apr_…</code>): the call,
          its arguments and provenance, and why it needs a person. Someone approves or denies
          it in the web app or through <code>POST /api/approvals/&#123;id&#125;/approve</code>{" "}
          and <code>/deny</code>. An approved call counts as clean evidence the next time
          permissions are drafted from traffic.
        </p>
        <p>
          Used in: <Link href="/docs/guides/approvals">Approvals and the kill switch</Link>,{" "}
          <Link href="/docs/app/approvals">the approval queue</Link>.
        </p>
      </Def>

      <Def id="proposal" term="Proposal (learned permissions)">
        <p>
          A change to governance configuration that the product drafts and a person decides.
          The kind you meet first is a grant or tool declaration drafted from traffic by{" "}
          <code>agentfox policy proposals from-traffic</code>. Limits and the provenance
          ceiling are read only from clean calls: ones refused only because nothing was
          configured, or approved by a person. Calls held for provenance shape neither, so an
          attacker&apos;s recipient never becomes a limit.
        </p>
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Means</th>
              <th>Moves to</th>
            </tr>
          </thead>
          <tbody>
            <tr><td><code>proposed</code></td><td>Filed.</td><td>proven, rejected, superseded</td></tr>
            <tr><td><code>proven</code></td><td>Replayed against the recorded calls it was drawn from.</td><td>approved, rejected, superseded</td></tr>
            <tr><td><code>approved</code></td><td>A person said yes (<code>proposals approve</code>).</td><td>canary, applied, rejected, superseded</td></tr>
            <tr><td><code>canary</code></td><td>Live for a cohort only.</td><td>applied, rolled_back</td></tr>
            <tr><td><code>applied</code></td><td>In force (<code>proposals apply</code>).</td><td>verified, rolled_back</td></tr>
            <tr><td><code>verified</code>, <code>rejected</code>, <code>rolled_back</code>, <code>superseded</code></td><td>Final.</td><td>—</td></tr>
          </tbody>
        </table>
        <p>
          A proposal that loosens a control is never applied by automation. Grants are scoped
          to one agent and need one approver; tool declarations apply to the whole
          organisation and need two different people.
        </p>
        <p>
          Used in: <Link href="/docs/quickstart">Quickstart</Link>,{" "}
          <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>,{" "}
          <Link href="/docs/guides/tuning">Tune detectors</Link>.
        </p>
      </Def>

      <Def id="control-points" term="Control points">
        <p>
          The same policies and the same decision record, bound in six places. Each sees a
          different surface, so connecting one does not cover the others.
        </p>
        <table>
          <thead>
            <tr>
              <th>Control point</th>
              <th>Connect with</th>
              <th>What it sees</th>
              <th>What it does not</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>SDK (Python)</td>
              <td><code>agentfox.auto()</code></td>
              <td>
                Every OpenAI, Anthropic, LiteLLM and LangChain model call in the process (sync,
                async, streamed): messages, response text, and each tool call in the response
                before your code runs it.
              </td>
              <td>The OpenAI Responses API; tools your code calls without the model asking.</td>
            </tr>
            <tr>
              <td>Gateway</td>
              <td><code>agentfox serve</code></td>
              <td>
                Model calls proxied through <code>/v1</code>, and whatever you ask about on{" "}
                <code>/v1/guard/*</code>: input, output, tool calls, memory writes, agent
                messages.
              </td>
              <td>Anything your code does not send to it.</td>
            </tr>
            <tr>
              <td>LangGraph</td>
              <td><code>AgentFoxGuard</code> node wrappers</td>
              <td>Retrieval, model and tool nodes; state survives checkpoints.</td>
              <td>Nodes you did not wrap.</td>
            </tr>
            <tr>
              <td>MCP</td>
              <td><code>agentfox scan mcp</code> and the governor</td>
              <td>
                Server configs before anything starts; at call time, each tool&apos;s digest
                against the one reviewed, and results as untrusted input.
              </td>
              <td>Servers no config declares.</td>
            </tr>
            <tr>
              <td>Hook (coding agents)</td>
              <td><code>agentfox admin hooks install</code></td>
              <td>
                Claude Code&apos;s <code>UserPromptSubmit</code>, <code>PreToolUse</code> (can
                stop the call) and <code>PostToolUse</code> (cannot withdraw it; marks the result
                untrusted).
              </td>
              <td>Anything off this machine, including a session running in the vendor&apos;s cloud.</td>
            </tr>
            <tr>
              <td>CLI</td>
              <td><code>agentfox scan</code>, <code>agentfox test</code>, <code>agentfox policy simulate</code></td>
              <td>Source code, configs, and recorded traffic replayed against a candidate.</td>
              <td>Live calls; it decides nothing at runtime.</td>
            </tr>
          </tbody>
        </table>
        <p>
          Guides: <Link href="/docs/guides/python-auto">Python</Link>,{" "}
          <Link href="/docs/guides/gateway">gateway</Link>,{" "}
          <Link href="/docs/guides/langgraph">LangGraph</Link>,{" "}
          <Link href="/docs/guides/mcp">MCP</Link>,{" "}
          <Link href="/docs/guides/coding-agents">coding agents</Link>,{" "}
          <Link href="/docs/guides/scan-a-repo">CLI and CI</Link>.
        </p>
      </Def>

      <Def id="evidence" term="Audit chain and evidence">
        <p>
          Every decision, grant, approval and operator action is appended to a hash chain:
          each entry carries the digest of the one before, and signed checkpoints are written
          over the head. Editing a row breaks every digest after it.
        </p>
        <Code>{`agentfox report verify`}</Code>
        <Output>{`chain: 215 entries, head seq 215, 2 checkpoints
CHAIN INTACT — 215 entries verified (seq 1..215)`}</Output>
        <p>
          An <b>evidence package</b> (<code>agentfox report evidence</code>) is a zip of the
          agents, traces, decisions, approvals, findings and chain rows for a period, with the
          one-page summary on top and a standalone <code>verify_chain.py</code> that re-derives
          every digest using only the Python standard library. Framework mappings inside it
          are labelled <code>DRAFT — UNVERIFIED / NOT LEGAL ADVICE</code> until a qualified
          reviewer signs them off.
        </p>
        <p>
          Used in: <Link href="/docs/guides/audit-evidence">Prove it to an auditor</Link>,{" "}
          <Link href="/docs/app/compliance">Compliance in the web app</Link>. The signing
          key is <code>AGENTFOX_AUDIT_SIGNING_KEY</code>; change it before any real
          deployment (<Link href="/docs/self-host">Self-hosting</Link>).
        </p>
      </Def>

      <NextSteps
        items={[
          { href: "/docs/guides/contain-tool-calls", label: "Contain tool calls", why: "put grants, provenance and declarations to work" },
          { href: "/docs/reference/policies", label: "Policy language", why: "the rule schema behind every effect above" },
          { href: "/docs/limits", label: "Limits", why: "where each of these stops working" },
        ]}
      />
    </article>
  );
}
