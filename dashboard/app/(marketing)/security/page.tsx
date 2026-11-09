import type { Metadata } from "next";
import Link from "next/link";

import { Arrow, LpFooter, LpNav } from "@/components/lp/parts";
import { publicPageMetadata, REPO_URL } from "@/lib/site";

export const dynamic = "force-dynamic";

export const metadata: Metadata = publicPageMetadata({
  title: "Security",
  description:
    "How to report a vulnerability in AgentFox privately, what is in scope, and what has not been independently audited yet.",
  path: "/security",
});

const SECURITY_MD = `${REPO_URL}/blob/main/SECURITY.md`;
const ADVISORIES = `${REPO_URL}/security/advisories/new`;
const SRC = `${REPO_URL}/blob/main`;

export default function Security() {
  return (
    <div className="lp">
      <LpNav />
      <main id="main" className="lp-page">
        <div className="lp-wrap">
          <h1>Security</h1>
          <p className="lp-lead">How to report a vulnerability, and what has and hasn&apos;t been checked.</p>

          <section>
            <h2>Report a vulnerability</h2>
            <p>
              Use <a href={ADVISORIES}>GitHub&apos;s private vulnerability reporting</a>, not a public issue or an email. Only the
              maintainers can see the report. A failing request, a policy file or a short script helps more than a description.
            </p>
            <p>
              <a href={SECURITY_MD}>SECURITY.md</a> is the full process. If this page and that file ever disagree, the file is right.
            </p>
            <div className="lp-actions">
              <a href={ADVISORIES} className="lp-btn lp-btn-primary lp-btn-sm">
                Report privately <Arrow />
              </a>
            </div>
          </section>

          <section>
            <h2>In scope</h2>
            <p>
              The enforcement path, the policy engine, the audit chain and its verifier, the gateway and its authentication, tenant
              isolation, and the hosted playground. For example: getting an action through that your grants refuse, reading or
              changing another tenant&apos;s data, forging or breaking the audit chain without the verifier noticing, or making a
              control fail open without recording it.
            </p>
          </section>

          <section>
            <h2>Not a vulnerability</h2>
            <ul>
              <li>
                A prompt injection a detector missed. Detection lowers the odds, it isn&apos;t a guarantee, and the miss rates are on the{" "}
                <Link href="/benchmark">benchmark</Link>. Report it as a wrong verdict on <Link href="/support">support</Link>.
              </li>
              <li>An attack that works because a tool was declared with the wrong impact. Containment is only as good as the declarations.</li>
            </ul>
          </section>

          <section>
            <h2>What the code enforces</h2>
            <ul>
              <li>
                Tenant isolation is attached to the database session, not to each query, so a new query can&apos;t forget it.{" "}
                <a href={`${SRC}/src/agentfox/core/tenancy.py`}>tenancy.py</a>
              </li>
              <li>
                The audit log is a hash chain with a standalone verifier that needs no database access and none of our code.{" "}
                <a href={`${SRC}/src/agentfox/platform/ledger/chain.py`}>chain.py</a>
              </li>
              <li>
                Four controls can&apos;t be configured to fail open: tenant isolation, entitlements, data-access scope and the audit
                chain. <a href={`${SRC}/src/agentfox/runtime/availability.py`}>availability.py</a>
              </li>
            </ul>
          </section>

          <section>
            <h2>Audits</h2>
            <p>
              There has been no third-party audit, penetration test, SOC 2 or ISO 27001 certification, and there is no bug bounty.
              What exists is the source, the tests and a verifier you can run yourself.
            </p>
          </section>
        </div>
      </main>
      <LpFooter />
    </div>
  );
}
