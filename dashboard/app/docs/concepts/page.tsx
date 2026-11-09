import type { Metadata } from "next";
import Link from "next/link";

import { Screenshot } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Core concepts",
  description:
    "The words the rest of the docs use: agent, project, tool and impact, access, where an argument came from, guardrails and rules, Watch and Block, issues and traces.",
  path: "/docs/concepts",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Core concepts</h1>
      <p className="docs-lede">The words the rest of the docs use, one short section each.</p>

      <h2 id="agent">Agent</h2>
      <p>
        A program that calls a model and can take actions. Each agent has a name, such as{" "}
        <code>support-triage</code>, and everything else (its access, its rules, its issues) hangs off
        that name. Agents come from a scan of your code, from <code>agentfox.auto()</code>, or from
        their own traffic. An agent seen in traffic that nobody added is flagged so someone can own it.
      </p>

      <h2 id="project">Project</h2>
      <p>
        An agent and every agent it hands work to. The Agents page draws one project as a map: who
        talks to each agent, its model, its tools, the data those tools touch, and the guardrail on
        each line.
      </p>
      <Screenshot {...SCREENS.agentMap} />

      <h2 id="tool">Tool and its impact</h2>
      <p>
        Anything an agent can call that is not the model: a function, an API, an MCP server, a shell.
        Each tool has an impact, which says how much harm a wrong call can do:
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Impact</th>
            <th>Means</th>
          </tr>
        </thead>
        <tbody>
          <tr><td><code>read</code></td><td>Reads data, changes nothing.</td></tr>
          <tr><td><code>write</code></td><td>Changes data, and the change can be undone.</td></tr>
          <tr><td><code>high_impact</code></td><td>Can be undone, but costly if wrong.</td></tr>
          <tr><td><code>irreversible</code></td><td>Cannot be taken back: sending, paying, deleting.</td></tr>
        </tbody>
      </table></div>
      <p>
        A new tool gets an impact guessed from its name and description, marked as a guess until a
        person confirms it.
      </p>

      <h2 id="access">Access</h2>
      <p id="grant">
        Which tools an agent may call. Access to a tool can carry limits on the arguments (an amount
        under 1,000, one email domain) and can require a person to approve each call. A call to a tool
        the agent was not given is refused once Tool containment blocks; while it watches, the call is
        recorded as what it would have stopped. You see and change it on the agent&apos;s{" "}
        <strong>Access</strong> tab. See <Link href="/docs/govern">Tool access</Link>.
      </p>

      <h2 id="provenance">Where an argument came from</h2>
      <p>
        AgentFox tracks where each value in a tool call came from: the user typed it, it came out of a
        retrieved document, out of another tool&apos;s result (a fetched web page), from another agent,
        or from the agent&apos;s memory. Anything not typed by the user is untrusted. An untrusted value
        headed for a tool that changes something is refused or held for a person, even when nothing
        looked like an attack. An email whose address was copied out of a web page is stopped because
        of where the address came from.
      </p>
      <p>
        Two settings change this. <span id="output-trust" />Declare a tool&apos;s output{" "}
        <code>trusted</code> when it is a system of record you control, such as your CRM, and values
        copied from it no longer count as untrusted. <span id="taint-scope" />
        <code>taint_scope</code> decides what counts: <code>session</code> (the default) marks every
        later call once the run has read anything untrusted; <code>argument</code> looks only at the
        values in the call itself, which lets more real work through and misses more attacks. See{" "}
        <Link href="/docs/reference/config">Configuration</Link>.
      </p>

      <h2 id="guardrails">Guardrails, rules, Watch and Block</h2>
      <p>
        A guardrail is a check on one line of the map: what users send, what the model replies, or a
        tool call. Rules are grouped into libraries you apply to agents, and you can write your own.
        Each runs in one of two modes:
      </p>
      <ul>
        <li>
          <strong>Watch</strong> records what the rule would have done and lets the call through.
        </li>
        <li>
          <strong>Block</strong> stops the call, hides the text, or holds it for a person.
        </li>
      </ul>
      <p>
        Every library starts in Watch, Tool containment included: look at what it would have stopped,
        then switch it to Block. Only destructive commands, turning AgentFox off, and a limit or Ask
        first set on a grant apply from the start. In the CLI, Watch is <code>observe</code> and Block
        is <code>enforce</code> (<code>agentfox policy enforce &lt;library&gt;</code>). See{" "}
        <Link href="/docs/protect">Guardrails</Link>.
      </p>

      <h2 id="issues">Issues</h2>
      <p id="findings">
        Something a person should look at: a blocked attack, a tool call that was stopped or would have
        been, an agent nobody owns. The same problem seen again is one issue with a count, not a new
        row. The CLI lists them with <code>agentfox findings</code>.
      </p>

      <h2 id="traces">Traces</h2>
      <p>
        One run end to end: the user&apos;s message, each model call, each tool call, and every check
        each one went through, with the reason for any block. Every decision is also written to a
        tamper-evident log, which is what <Link href="/docs/prove/audit">audit evidence</Link> is built
        from.
      </p>
    </article>
  );
}
