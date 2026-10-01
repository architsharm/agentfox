import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Audit trail",
  description: "Findings, doctor, a chain you can re-derive, and an export an auditor can check.",
  path: "/docs/evidence",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>Audit trail</h1>
      <p>
        Every allow and every block is a record. The chain is tamper-evident: each
        record carries the hash of the one before it. There is no update or delete path
        for an entry.
      </p>

      <h2>What a person should look at</h2>
      <pre>
        <code>{`agentfox findings
agentfox findings --severity high
agentfox doctor`}</code>
      </pre>
      <p>
        <code>findings</code> lists shadow agents, agents with no accountable owner,
        stale identities, and detections that led to a block or a redaction.{" "}
        <code>doctor</code> grades the configuration. A healthy run still prints the
        inconvenient lines: authentication accepting the development header, and a
        detector that times out failing open and recording the gap. Those are about
        AgentFox, not about your agents.
      </p>

      <h2>Check the chain</h2>
      <pre>
        <code>agentfox audit verify</code>
      </pre>
      <p>
        Re-derives the hash chain and exits 1 if it is broken. The demo does this, then
        edits an entry directly in the database, then verifies again. The second check
        reports the chain tampered, with <code>payload_mismatch</code> on the edited
        sequence. Removing an entry breaks the chain from that point on.
      </p>

      <h2>Export</h2>
      <pre>
        <code>agentfox evidence export --agent support-triage --from 2026-08-01 --to 2026-09-30</code>
      </pre>
      <p>
        The package is the records for that agent and date range, the policy that
        produced them, and the versions of everything that took part. It ships with a
        standard-library <code>verify_chain.py</code>, so an auditor re-derives the
        hash chain without importing AgentFox and without calling the API.
      </p>
      <p>
        Compliance status, which reads this record rather than a form, is on{" "}
        <Link href="/docs/compliance">Compliance</Link>.
      </p>
    </article>
  );
}
