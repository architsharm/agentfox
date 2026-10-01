import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Limits",
  description: "What is only as good as your declarations, and what is not built yet.",
  path: "/docs/limits",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Help</p>
      <h1>Limits</h1>
      <p>
        Written here so they are not discovered later. Live per-area coverage is
        computed by probe in <code>docs/status.md</code> in the repository, not asserted
        on this page.
      </p>
      <h2>It is only as good as the declarations</h2>
      <p>
        A destructive tool declared <code>read</code> is not treated as destructive by
        anything downstream. For a shell, <code>ls</code> and <code>rm -rf</code> are
        the same tool, so the impact tier is a floor. <code>agentfox doctor</code>{" "}
        grades the declarations. <code>agentfox check</code> finds tools you have not
        declared.
      </p>
      <h2>You declare the estate yourself</h2>
      <p>
        There is no Okta connector and no DataHub connector. Principals, grants, and
        source tiers live in AgentFox. The seams for those integrations exist. The
        integrations do not.
      </p>
      <h2>Compliance mappings are drafts</h2>
      <p>
        The 43 controls are mapped to the EU AI Act, ISO 42001, NIST AI RMF, SOC 2,
        OWASP LLM, OWASP Agentic, and MITRE ATLAS by engineers, from the framework
        texts. They have not been reviewed by counsel. Evidence packages label the
        mappings <code>DRAFT — UNVERIFIED / NOT LEGAL ADVICE</code> rather than leaving
        them out. Status is computed from what the agent did. It is not a certification.
        The command is on <Link href="/docs/compliance">Compliance</Link>.
      </p>
      <h2>Version 0.3</h2>
      <p>
        No live identity provider or SSO. Multi-tenancy is a single organisation,
        enforced at the session. Text only. Each of those is a known gap with a seam
        already in place.
      </p>
      <h2>A hook only sees this machine</h2>
      <p>
        Claude Code hooks govern the agent on the laptop they are installed on. Anything
        that does not go through that harness is not covered, and a session that runs
        in the vendor&apos;s cloud is not visible to them at all.
      </p>
      <p>
        Detection&apos;s own misses are on <Link href="/docs/benchmarks">Benchmarks</Link>.
      </p>
    </article>
  );
}
