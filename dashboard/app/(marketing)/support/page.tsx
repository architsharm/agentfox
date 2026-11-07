import type { Metadata } from "next";
import Link from "next/link";

import { Arrow, LpFooter, LpNav } from "@/components/lp/parts";
import { publicPageMetadata, REPO_URL, SUPPORT_EMAIL } from "@/lib/site";

export const dynamic = "force-dynamic";

export const metadata: Metadata = publicPageMetadata({
  title: "Support",
  description: "Where to ask a question about AgentFox, report a bug or a wrong verdict, and how to reach us about a rollout.",
  path: "/support",
});

const NEW_ISSUE = `${REPO_URL}/issues/new/choose`;
const DISCUSSIONS = `${REPO_URL}/discussions`;

const ROUTES: [string, string, string][] = [
  ["It crashed, hung or contradicted the docs", "Bug report", "The command and its output, version, Python and OS."],
  ["It blocked something it shouldn't have, or allowed an attack", "Wrong verdict", "Trace id, rule id, policy pack and mode, and what was being checked."],
  ["It can't do something you need", "Feature request", "What you were governing and where it ran out."],
  ["A question, or is this the right tool", "Discussions", "Anything. Keeps the issue list to things to fix."],
  ["A vulnerability", "Private report", "Never a public issue. See the security page."],
];

export default function Support() {
  return (
    <div className="lp">
      <LpNav />
      <main className="lp-page">
        <div className="lp-wrap">
          <h1>Support</h1>
          <p className="lp-lead">
            Questions and bugs go on GitHub. For help with a rollout, email{" "}
            <a href={`mailto:${SUPPORT_EMAIL}`} style={{ color: "var(--af-brand)" }}>
              {SUPPORT_EMAIL}
            </a>
            .
          </p>
          <div className="lp-actions" style={{ justifyContent: "flex-start", marginTop: 24 }}>
            <a href={NEW_ISSUE} className="lp-btn lp-btn-primary lp-btn-sm">
              Open an issue <Arrow />
            </a>
            <a href={DISCUSSIONS} className="lp-btn lp-btn-secondary lp-btn-sm">
              Ask in Discussions
            </a>
          </div>

          <section>
            <h2>Where it goes</h2>
            <table>
              <thead>
                <tr>
                  <th>What happened</th>
                  <th>Template</th>
                  <th>Include</th>
                </tr>
              </thead>
              <tbody>
                {ROUTES.map(([what, where, include]) => (
                  <tr key={what}>
                    <td>{what}</td>
                    <td>{where === "Private report" ? <Link href="/security">{where}</Link> : where}</td>
                    <td>{include}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Redact first</h2>
            <p>
              GitHub issues are public. Don&apos;t paste real prompts, tool arguments, documents or audit rows. Replace names, accounts,
              URLs and secrets with placeholders. For a wrong verdict, the trace id and rule id matter more than the message itself.
            </p>
          </section>

          <section>
            <h2>Response times</h2>
            <p>
              Issues and Discussions are answered on a best-effort basis, with no promised reply time. If you&apos;re rolling AgentFox
              out and need a named contact and priority on fixes, email us. That isn&apos;t priced yet; see{" "}
              <Link href="/pricing">pricing</Link>.
            </p>
          </section>

          <section>
            <h2>Before you ask</h2>
            <p>
              The <Link href="/docs/quickstart">quickstart</Link> and <Link href="/docs/support">troubleshooting</Link> pages in the
              docs answer most setup questions.
            </p>
          </section>
        </div>
      </main>
      <LpFooter />
    </div>
  );
}
