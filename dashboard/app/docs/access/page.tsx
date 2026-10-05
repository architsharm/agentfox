import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Access control",
  description:
    "Let AgentFox propose grants from what your agent called, or declare a tool and grant a capability by hand, and read the three verdicts.",
  path: "/docs/access",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>Access control</h1>
      <p>
        You write down what each tool can do, and which agent may call it, before the
        agent runs. A prompt cannot add to that. Anything not granted is refused. That
        is the default, which is why the first{" "}
        <Link href="/docs/connect">tool-call check</Link> for an unknown agent is{" "}
        <code>block</code>.
      </p>

      <h2>Watch, then let it propose the grants</h2>
      <p>
        You do not have to write the grants from memory. Run the agent as it is. Every
        refused call is recorded with its tool, its arguments and where each argument
        came from, and one command turns that into proposals:
      </p>
      <pre>
        <code>{`agentfox proposals from-traffic --agent support-bot
agentfox proposals approve <id> --actor you@example.com --note "matches its job"
agentfox proposals apply <id> --actor you@example.com`}</code>
      </pre>
      <p>
        It files a declaration for each tool nobody declared, with an impact guessed from
        the name, and one grant per tool the agent called, in plain English: &ldquo;Let
        support-bot call issue_refund with amount &le; 120 (seen 5 times, max 112)&rdquo;.
        The limits are read off the calls. It learns only from calls that were refused
        for configuration, never from a call a detector matched or one that broke a
        limit. A call stopped for where its arguments came from shapes the limits but not
        the provenance ceiling until a person approves it in the approval queue; the next
        run then proposes raising the ceiling. Every proposal widens what the agent may
        do, so a person approves each one, and tool declarations, which apply to the whole
        organisation, need two people. Nothing is applied by automation. Undo any of them
        with <code>agentfox proposals rollback</code>.
      </p>
      <p>
        The refusal itself says this: a default-deny block names the agent, the tool, and
        both commands.
      </p>

      <h2>Declare the tool</h2>
      <pre>
        <code>agentfox declare tool payments.transfer --impact irreversible</code>
      </pre>
      <p>
        Impact is <code>none</code>, <code>read</code>, <code>write</code>, or{" "}
        <code>irreversible</code>. The declaration is a floor. For a shell,{" "}
        <code>ls</code> and <code>rm -rf</code> are the same tool, and a destructive
        tool declared <code>read</code> is not treated as destructive by anything
        downstream.
      </p>
      <p>
        A tool&rsquo;s output is untrusted by default: a value an agent copies out of it
        into another tool&rsquo;s arguments counts as <code>tool_result</code>. For a
        system of record you control, such as a CRM read, say so, and an email address
        copied out of it into <code>send_email</code> stops counting as untrusted input:
      </p>
      <pre>
        <code>agentfox tools declare read_customer_record --impact read --output-trust trusted</code>
      </pre>

      <h2>Grant it, with limits</h2>
      <pre>
        <code>{`agentfox permit grant my-agent payments.transfer \\
    --limit amount:lt=1000 --max-taint user
agentfox permit list my-agent
agentfox permit revoke <capability-id>`}</code>
      </pre>
      <p>
        <code>capability grant</code> is the only command that widens least privilege.
        It prints what it is about to allow and asks before it writes, then records the
        grant in the audit chain. Pass <code>--yes</code> in scripts.{" "}
        <code>--max-taint user</code> means arguments a person typed may proceed.
        Anything that came out of a document or another tool needs a person. The ladder,
        worst last, is <code>none</code>, <code>user</code>, <code>retrieved</code>,{" "}
        <code>tool_result</code>, <code>subagent</code>, <code>memory</code>.
      </p>
      <p>
        A ceiling above <code>user</code> is a statement about this agent and this tool,
        and the provenance rules respect it: within the ceiling,{" "}
        <code>taint.irreversible_tool</code> does not overrule the grant. One rule does
        not defer. <code>composition.escalation</code> blocks a value produced by a
        lower-impact tool and passed into a higher-impact one, because a grant says what
        kind of content may reach a tool, not which tool may feed it. Declaring the
        producing tool&rsquo;s output trusted is how you say that flow is intended, and{" "}
        <code>capability grant</code> tells you so when you set a ceiling.
      </p>

      <h2>Session or argument provenance</h2>
      <p>
        One setting decides what a tool call&rsquo;s provenance is:{" "}
        <code>taint_scope</code> in <code>agentfox.toml</code>, or{" "}
        <code>AGENTFOX_TAINT_SCOPE</code>. <code>session</code>, the default, takes the
        worst untrusted content anywhere in the run so far: once the agent has read a web
        page, every later irreversible call carries it, even one with no arguments.{" "}
        <code>argument</code> takes only what the call&rsquo;s own arguments were copied
        from. Session contains more attacks and escalates more legitimate calls; argument
        lets more legitimate work through and misses an attack whose payload never lands
        in an argument. Every published number was measured under <code>session</code>.
      </p>

      <h2>The same call, three answers</h2>
      <p>
        After the grant above, three calls to <code>payments.transfer</code> for{" "}
        <code>my-agent</code>:
      </p>
      <table>
        <thead>
          <tr>
            <th>Call</th>
            <th>Verdict</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>amount 250, provenance user</td>
            <td>allow</td>
            <td>Inside the grant.</td>
          </tr>
          <tr>
            <td>amount 250, provenance tool_result</td>
            <td>escalate</td>
            <td>
              <code>taint.irreversible_tool</code>. Same tool, same amount. The value
              came from something untrusted. No detector was involved.
            </td>
          </tr>
          <tr>
            <td>amount 5000, provenance user</td>
            <td>block</td>
            <td>
              <code>capability.constraint_violated</code>. Over the argument limit. The
              reason names the limit and the amount.
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        An <code>escalate</code> verdict returns an <code>approval_id</code>. Poll{" "}
        <code>GET /api/approvals/{"{id}"}</code>, or decide it from the dashboard or the
        CLI. The other grant shape from the command list, a closed set of argument
        values, is <code>--limit priority:in=low,normal</code>.
      </p>
    </article>
  );
}
