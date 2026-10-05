import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Commands",
  description: "The CLI grouped by what you are trying to do.",
  path: "/docs/commands",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>Commands</h1>
      <p>
        The same list as the README, grouped by the job. Flags that change what a
        command means are on the page for that job.
      </p>

      <h2>Find out what you already have</h2>
      <pre>
        <code>{`agentfox scan --sessions
agentfox scan
agentfox agents list
agentfox scan runtime
agentfox agents lineage payments-ops
agentfox scan mcp internal-tools --seed-fixture`}</code>
      </pre>
      <p>
        <code>quickscan</code> is the zero-config first look. Nothing leaves the machine.{" "}
        <code>check</code> scans a repository for what talks to a model, and what of that
        is ungoverned. <code>--file</code> on <code>scan mcp</code> takes a real{" "}
        <code>tools/list</code>. Detail is on <Link href="/docs/discovery">Discovery</Link>.
      </p>

      <h2>Bound what an agent is allowed to do</h2>
      <pre>
        <code>{`agentfox declare tool billing.export --impact write
agentfox permit grant support-triage tickets.close \\
    --limit priority:in=low,normal --max-taint user
agentfox permit list support-triage
agentfox permit revoke <capability-id>`}</code>
      </pre>
      <p>
        Impact is <code>none</code>, <code>read</code>, <code>write</code>, or{" "}
        <code>irreversible</code>. <code>--max-taint</code> is the worst provenance an
        argument may carry and still go through without an approval: <code>none</code>,{" "}
        <code>user</code>, <code>retrieved</code>, <code>tool_result</code>,{" "}
        <code>subagent</code>, <code>memory</code>. <code>capability grant</code> is the
        only command that widens least privilege, so it confirms before it writes.{" "}
        <code>--yes</code> skips the prompt in CI. Anything not listed by{" "}
        <code>capability list</code> is refused.
      </p>

      <h2>See what happened</h2>
      <pre>
        <code>{`agentfox findings
agentfox findings --severity high
agentfox doctor
agentfox report verify
agentfox report evidence --agent support-triage --from 2026-08-01 --to 2026-09-30`}</code>
      </pre>
      <p>
        <code>audit verify</code> re-derives the chain and exits 1 if it is broken.
        The export and the verifier are on <Link href="/docs/evidence">Audit trail</Link>.
      </p>

      <h2>Test before you trust</h2>
      <pre>
        <code>{`agentfox test run support-quality
agentfox test gate support-quality
agentfox test redteam support-triage
agentfox policy lint
agentfox policy simulate --file candidate.yaml`}</code>
      </pre>
      <p>
        <code>eval gate</code> exits 1 on a regression and is meant for CI.{" "}
        <code>policy lint</code> exits 1 on a critical or high finding. What each one
        establishes is on <Link href="/docs/test">Test</Link>.
      </p>

      <h2>Run it</h2>
      <pre>
        <code>{`agentfox serve
agentfox admin auth issue you@example.com
agentfox admin db upgrade
agentfox policy effective --agent support-triage
agentfox policy list
agentfox policy enforce baseline
agentfox policy observe baseline
agentfox report status --framework eu-ai-act
agentfox agents quarantine support-triage --reason "investigating"
agentfox agents resume support-triage`}</code>
      </pre>
      <p>
        <code>serve</code> is the gateway and the control-plane API, on{" "}
        <code>127.0.0.1:8080</code>. <code>policy enforce baseline</code> is the step
        that starts blocking model traffic. <code>policy observe baseline</code> puts
        it back. <code>quarantine</code> is the kill switch for one agent, and it is
        reversible.
      </p>
    </article>
  );
}
