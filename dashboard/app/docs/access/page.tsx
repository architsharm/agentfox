import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Access control",
  description: "Declare a tool, grant a capability with argument limits, and read the three verdicts.",
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
              <code>capability.denied</code>. Over the argument limit.
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
