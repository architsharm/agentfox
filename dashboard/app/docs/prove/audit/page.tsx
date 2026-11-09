import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { Tab, Tabs } from "@/components/docs/tabs";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Audit evidence",
  description:
    "A one-page summary of what your agents did, a tamper-evident audit log, control status against the EU AI Act, ISO 42001, SOC 2 and others, and evidence packages an auditor verifies without AgentFox.",
  path: "/docs/prove/audit",
});

const cli = (path: string) => `/docs/reference/cli#cmd-${path}`;

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Audit evidence</h1>
      <p className="docs-lede">
        Show someone else what your agents did and what was stopped, in a form they can check without
        trusting you.
      </p>

      <Callout kind="note" title="Enterprise">
        Compliance (control status, frameworks, sign-off, risk register) and evidence packages are
        AgentFox Enterprise. The summary, the audit log and retention are in the open core. Enterprise
        runs free in production for one workspace with up to four agents.
      </Callout>

      <Steps topLevel>
        <Step title="Share the summary">
          <p>
            <strong>Reports → Summary</strong> is one page for someone who has never opened AgentFox:
            what is running, what was stopped, and what rules in Watch would have stopped. Press{" "}
            <strong>Print / save as PDF</strong> to send it on.
          </p>
          <Code>{`agentfox report summary --since 30d --format html --out summary.html`}</Code>
        </Step>

        <Step title="Check the audit log">
          <p>
            Every decision, approval and change is written to a hash-chained log. An edited or deleted
            entry breaks the chain. On <strong>Reports → Audit log</strong>, press{" "}
            <strong>Verify log</strong>.
          </p>
          <Code>{`agentfox report verify`}</Code>
          <p>
            It exits 1 on a break, so you can run it on a schedule and alert on it.
          </p>
        </Step>

        <Step title="See control status (Enterprise)">
          <p>
            <strong>Reports → Compliance</strong> maps 44 controls to the EU AI Act, ISO/IEC 42001,
            NIST AI RMF, SOC 2, OWASP and MITRE ATLAS. Each control&apos;s status is computed from your
            own traffic, not filled in on a form. <strong>Regulations</strong> shows each framework;{" "}
            <strong>Risk register</strong> holds one assessment per agent.
          </p>
          <Screenshot {...SCREENS.reports} />
        </Step>

        <Step title="Build an evidence package (Enterprise)">
          <Tabs>
            <Tab label="In the app">
              <p>
                On <strong>Reports → Evidence</strong>, choose the agents and period and press{" "}
                <strong>Build</strong>. <strong>Download</strong> gives you a zip.
              </p>
            </Tab>
            <Tab label="CLI">
              <Code>{`agentfox admin checkpoint
agentfox report evidence --agent payments-ops --since-days 30`}</Code>
            </Tab>
          </Tabs>
          <p>
            The zip holds the audit log, decisions, approvals, issues, control status and a summary.
            The auditor unzips it and runs <code>python3 verify_chain.py</code> with any Python 3: no
            AgentFox, no call to your server. Building a package is itself written to the audit log.
          </p>
        </Step>
      </Steps>

      <h2>Framework mappings are drafts</h2>
      <p>
        Engineers mapped controls to clauses from the published texts. No counsel has reviewed them,
        and they are not legal advice. Each one is labelled <code>DRAFT — UNVERIFIED</code> until a
        named person signs it off: open a control on <strong>Compliance</strong> and use{" "}
        <strong>Record a review</strong> (written to the audit log, valid for 90 days), or hand the
        reviewer <Link href={cli("report-review-packet")}><code>agentfox report review-packet</code></Link>.
      </p>

      <h2>Before you show checkpoints to anyone</h2>
      <p>
        Checkpoints are signed anchors over the log. Out of the box they use a published development
        key, so set <code>AGENTFOX_AUDIT_SIGNING_KEY</code> from your secret store first. Give the
        auditor the key separately; with it, <code>verify_chain.py</code> also checks the signatures.
      </p>

      <h2>Retention and legal hold</h2>
      <p>
        <strong>Settings → Retention</strong> sets how long each kind of data is kept. A daily job
        deletes older runs and redacts old content; the audit log is never purged. A legal hold stops
        the purge for the agents it names, or for everything. Both changes are recorded on the audit
        log.
      </p>

      <h2>If something goes wrong</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Every compliance count is zero</td>
            <td>
              Press <strong>Load control catalog</strong>, or run <code>agentfox admin catalog sync</code>.
            </td>
          </tr>
          <tr>
            <td>A control reads not implemented</td>
            <td>Nothing in the window used it. It needs real traffic, not a recompute.</td>
          </tr>
          <tr>
            <td>The package is nearly empty</td>
            <td>Nothing was recorded in that period, or the agents don&apos;t run through AgentFox.</td>
          </tr>
          <tr>
            <td>
              <code>checkpoint_signature</code> from <code>verify_chain.py</code>
            </td>
            <td>The key is not the one the checkpoints were signed with.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: cli("report"), label: "report in the CLI reference", why: "status, frameworks, risk, obligations, board, signoff" },
          { href: "/docs/reference/owasp", label: "OWASP Agentic Top 10", why: "what is covered, partly covered, or not" },
          { href: "/docs/limits", label: "Limits", why: "what the evidence cannot show" },
        ]}
      />
    </article>
  );
}
