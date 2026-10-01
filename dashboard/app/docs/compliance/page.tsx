import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Compliance",
  description: "Read control status from what the agent did. The mappings are engineering drafts.",
  path: "/docs/compliance",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>Compliance</h1>
      <p>
        43 controls, mapped to the EU AI Act, ISO 42001, NIST AI RMF, SOC 2, OWASP LLM,
        OWASP Agentic, and MITRE ATLAS. A control&apos;s standing comes from what the
        agent did: whether the rule existed, whether it fired, and whether the chain is
        intact. A control whose evidence source produces nothing reads{" "}
        <code>not_implemented</code>. Nobody ticks a box.
      </p>
      <pre>
        <code>{`agentfox compliance status
agentfox compliance status --framework eu-ai-act
agentfox evidence export --agent support-triage --from 2026-08-01 --to 2026-09-30`}</code>
      </pre>
      <p>
        The export is the same package as the <Link href="/docs/evidence">audit trail</Link>,
        including <code>verify_chain.py</code>, which recomputes the chain without
        importing AgentFox.
      </p>
      <h2>These mappings are drafts</h2>
      <p>
        Engineers produced them from the framework texts. Counsel has not reviewed them.
        Evidence packages label them <code>DRAFT — UNVERIFIED / NOT LEGAL ADVICE</code>{" "}
        rather than leaving them out. This is not a certification, and a mapping you
        cannot check independently is not one you should accept.
      </p>
    </article>
  );
}
