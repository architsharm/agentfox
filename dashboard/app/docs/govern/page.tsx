import type { Metadata } from "next";
import Link from "next/link";

import { Code, DemoAgentNames, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { Tab, Tabs } from "@/components/docs/tabs";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Tool access",
  description:
    "Choose which tools each agent may call, limit their arguments, require a person's approval, and draft access from what the agent really did.",
  path: "/docs/govern",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Tool access</h1>
      <p className="docs-lede">
        Decide which tools each agent may call and with what, so a model that has been talked into
        something still cannot do it.
      </p>

      <DemoAgentNames />

      <Steps topLevel>
        <Step title="See what an agent may call">
          <p>
            Open an agent and choose <strong>Access</strong>. Each row is a tool it may call, with its
            risk, its limits, and how often it was used. Any tool not listed is refused.
          </p>
          <Screenshot {...SCREENS.agentAccess} />
        </Step>

        <Step title="Allow what it tried">
          <p>
            <strong>Tried but not allowed</strong> lists the tools the agent called and was refused. Press{" "}
            <strong>Allow</strong> on each one it should have, or <strong>Allow all</strong>. This is the
            quickest way to draft access from real traffic.
          </p>
          <Tabs>
            <Tab label="In the app">
              <p>
                <strong>Found in its code</strong> lists the tools the scan saw but nobody allowed yet. To add
                any other tool, pick it in <strong>Add a tool…</strong> and press <strong>Allow</strong>.
              </p>
            </Tab>
            <Tab label="CLI">
              <p>Draft grants from the recorded calls. Each one waits for a person to approve and apply it.</p>
              <Code>{`agentfox policy proposals from-traffic --agent support-triage`}</Code>
            </Tab>
          </Tabs>
        </Step>

        <Step title="Limit a tool">
          <p>
            Click <strong>No limits · add</strong> on a row, press <strong>+ Limit</strong>, and fill in an
            argument, a comparison and a value, for example <code>rows ≤ 5000</code>. Press{" "}
            <strong>Save</strong>. A call outside the limit is refused.
          </p>
          <Tabs>
            <Tab label="In the app">
              <p>Every change saves at once and is written to the audit log.</p>
            </Tab>
            <Tab label="CLI">
              <Code>{`agentfox permit grant support-triage billing.export --limit 'rows:lte=5000' --yes`}</Code>
            </Tab>
          </Tabs>
        </Step>

        <Step title="Require approval">
          <p>
            Set the row&apos;s <strong>Permission</strong> to <strong>Ask first</strong>. Every call to that
            tool now waits on <Link href="/docs/govern/approvals">Approvals</Link> until a person approves
            or denies it.
          </p>
          <Tabs>
            <Tab label="In the app">
              <p>For a tool in Tried but not allowed, press <strong>Allow with approval</strong>.</p>
            </Tab>
            <Tab label="CLI">
              <Code>{`agentfox permit grant support-triage email.send --requires-approval --yes`}</Code>
            </Tab>
          </Tabs>
        </Step>
      </Steps>

      <h2 id="impact">Tool impact</h2>
      <p>
        Each tool has an impact, guessed from its name and description. Check it in the{" "}
        <strong>Risk</strong> column: a tool that moves money but is marked Read only is not protected.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Risk</th>
            <th>When an argument came from untrusted content</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Read only</td><td>The call goes through.</td></tr>
          <tr><td>Writes</td><td>Held for approval if the value came from another tool&apos;s output or worse.</td></tr>
          <tr><td>High impact</td><td>Held for approval unless the user typed it.</td></tr>
          <tr><td>Irreversible</td><td>Held for approval unless the user typed it.</td></tr>
        </tbody>
      </table></div>
      <p>
        A value copied out of a lower-impact tool&apos;s output into a higher-impact tool is refused
        outright. If that flow is intended, for example an address from your own CRM, mark the CRM
        tool&apos;s output trusted with{" "}
        <Link href="/docs/reference/cli#cmd-declare-tool">agentfox declare tool</Link>.
      </p>

      <h2 id="provenance">Where an argument came from</h2>
      <p>
        <strong>Accepts values from</strong> sets the most a tool trusts. A value from further down the
        list than the setting allows sends the call for approval. See{" "}
        <Link href="/docs/concepts#provenance">Core concepts</Link>.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Setting</th>
            <th>Allows values that</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>User input (default)</td><td>a person typed</td></tr>
          <tr><td>+ documents</td><td>also came from a retrieved document</td></tr>
          <tr><td>+ tool output</td><td>also came out of another tool</td></tr>
          <tr><td>+ other agents</td><td>also came from a sub-agent</td></tr>
          <tr><td>Anything</td><td>came from anywhere, memory included</td></tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/govern/approvals", label: "Approvals and the kill switch", why: "decide held calls; stop an agent" },
          { href: "/docs/reference/cli#cmd-permit-grant", label: "agentfox permit grant reference", why: "every limit operator and option" },
        ]}
      />
    </article>
  );
}
