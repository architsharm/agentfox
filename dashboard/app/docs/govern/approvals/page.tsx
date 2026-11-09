import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { Tab, Tabs } from "@/components/docs/tabs";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Approvals and the kill switch",
  description:
    "Approve or deny a tool call held for a person, and pause or stop an agent at once while you find out what it did.",
  path: "/docs/govern/approvals",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Approvals and the kill switch</h1>
      <p className="docs-lede">
        Decide the calls an agent is waiting on, and stop an agent outright when something looks wrong.
      </p>

      <h2>Approve a held call</h2>
      <Steps>
        <Step title="Open Approvals">
          <p>
            A call lands on <strong>Approvals</strong> when its tool is set to <strong>Ask first</strong>, or
            when an argument came from somewhere the tool does not trust (see{" "}
            <Link href="/docs/govern#provenance">Tool access</Link>). Each card shows the agent, the tool,
            the exact arguments, and why it was held. An argument from untrusted content is marked.
          </p>
          <Screenshot {...SCREENS.approvals} />
        </Step>

        <Step title="Approve or deny">
          <Tabs>
            <Tab label="In the app">
              <p>
                Press <strong>Approve</strong> or <strong>Deny</strong>. Deciding needs the owner, admin or
                security role. <strong>History</strong> lists every decision and who made it.
              </p>
            </Tab>
            <Tab label="CLI">
              <Code>{`agentfox permit approvals list
agentfox permit approvals approve apr_… -r "Finance asked for it"`}</Code>
            </Tab>
          </Tabs>
          <p>
            Approving lets exactly one call through: the same agent, tool and arguments, when the agent
            tries again within 30 minutes. Different arguments are held again. Denying sticks: the same
            call retried within 30 minutes (same agent, tool and arguments) is blocked with your reason,
            whether or not it presents the approval id, so it is not asked again.
          </p>
        </Step>
      </Steps>

      <Callout kind="warning" title="Who is told">
        With a Slack channel connected under Settings → Alerts (Enterprise), every held call is posted
        there with a link to approve or deny it. Without one nobody is told, so someone has to watch the
        Approvals page. There is no email. A call nobody decides is denied after 30 minutes
        (<code>AGENTFOX_APPROVAL_TTL_MINUTES</code> on the gateway).
      </Callout>

      <h2 id="kill-switch">Pause or stop an agent</h2>
      <Steps>
        <Step title="Pause or stop it">
          <p>
            Open the agent and press <strong>Pause ▾</strong> in its header. Choose{" "}
            <strong>Pause…</strong> while you investigate, or <strong>Stop…</strong> to record an incident.
            Both refuse every call the agent makes from the next one on. Give a reason: it goes in the
            audit log.
          </p>
          <Screenshot {...SCREENS.killSwitch} />
          <Tabs>
            <Tab label="In the app">
              <p>Pause needs owner, admin, security or developer. Stop needs owner, admin or security.</p>
            </Tab>
            <Tab label="CLI">
              <Code>{`agentfox agents quarantine support-triage --reason "odd exports"
agentfox agents kill support-triage --reason "confirmed"`}</Code>
            </Tab>
          </Tabs>
        </Step>

        <Step title="Deny what it left waiting">
          <p>
            Calls already on Approvals survive a pause. Deny the agent&apos;s waiting calls so nobody
            approves one by mistake.
          </p>
        </Step>

        <Step title="Resume">
          <p>
            Fix the cause, for example narrow a tool on <strong>Access</strong>, then press{" "}
            <strong>Resume</strong> on the banner. Resume needs owner, admin or security.
          </p>
          <Code>{`agentfox agents resume support-triage --reason "grant narrowed"`}</Code>
        </Step>
      </Steps>

      <h2>What a stopped agent can still do</h2>
      <ul>
        <li>A call that already passed the check finishes. The next one is refused.</li>
        <li>
          Only calls that go through AgentFox are stopped. Message checks on{" "}
          <code>/v1/guard/input</code> and <code>/v1/guard/output</code> do not read the switch, so gate
          tool calls through <code>/v1/guard/tool_call</code>.
        </li>
      </ul>

      <h2 id="handoffs">Conversations that should reach a person</h2>
      <p>
        <strong>Approvals → Human hand-offs</strong> lists conversations where a user asked for a person,
        got angry or kept failing, and whether someone picked them up. It is checked after the
        conversation, not during it.
      </p>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "choose which tools ask first" },
          { href: "/docs/reference/cli#cmd-permit-approvals-list", label: "agentfox permit approvals reference", why: "list, show, approve, deny" },
        ]}
      />
    </article>
  );
}
