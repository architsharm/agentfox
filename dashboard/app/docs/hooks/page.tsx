import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Coding agent hooks",
  description: "Three Claude Code hooks, which two can stop a call, and the warm daemon.",
  path: "/docs/hooks",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>Coding agents</h1>
      <p>
        Claude Code has three hook points. Two can stop something. The third cannot,
        because the side effect has already happened, and the product says so rather
        than reporting that event as a gate.
      </p>
      <pre>
        <code>{`agentfox hooks daemon
agentfox hooks install --agent my-agent --write
agentfox hooks status`}</code>
      </pre>
      <p>
        <code>hooks install --write</code> writes <code>.claude/settings.json</code>.
        A hook runs in a process the harness creates and destroys per call, so it talks
        to a warm daemon over a private Unix socket: about 3.9 seconds cold, about 6
        milliseconds warm. <code>hooks status</code> prints each event, what a refusal
        does, how that was established, and against which version.
      </p>
      <table>
        <thead>
          <tr>
            <th>Event</th>
            <th>What it sees</th>
            <th>What a refusal does</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>UserPromptSubmit</code></td>
            <td>The turn you submitted</td>
            <td>Stops it reaching the model</td>
          </tr>
          <tr>
            <td><code>PreToolUse</code></td>
            <td>The call about to run</td>
            <td>Stops the call, or rewrites its arguments</td>
          </tr>
          <tr>
            <td><code>PostToolUse</code></td>
            <td>What the tool returned</td>
            <td>Cannot withdraw the call. Tells the model the result is untrusted</td>
          </tr>
        </tbody>
      </table>
      <p>
        <code>PreToolUse</code> and <code>PostToolUse</code> were probed against a live
        session. <code>UserPromptSubmit</code> was read in the shipped bundle. An event
        nobody has checked has no row.
      </p>
      <pre>
        <code>agentfox policy observe coding-agent</code>
      </pre>
      <p>
        That pack is built for this job. A coding agent reads diffs, stack traces, and
        JSON, so instruction-shaped English in a tool result is caught at a threshold
        that would be wrong for a support agent.
      </p>
      <h2>What a hook is not</h2>
      <p>
        It governs the agent on this machine. Anything that does not go through this
        harness is not covered, and a session that runs in the vendor&apos;s cloud
        rather than on the laptop is not visible to it at all.
      </p>
      <p>
        The same product, packaged as Claude Code skills and slash commands, is the{" "}
        <Link href="/docs/harness">harness</Link>.
      </p>
    </article>
  );
}
