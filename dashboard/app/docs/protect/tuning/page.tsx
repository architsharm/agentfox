import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { Tab, Tabs } from "@/components/docs/tabs";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Fix false positives",
  description:
    "When a guardrail blocks a real user: find the run, mark the detection wrong, then lower the sensitivity or add an exception, checked against recent traffic first.",
  path: "/docs/protect/tuning",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Fix false positives</h1>
      <p className="docs-lede">
        A guardrail blocked something it should not have. Mark it, then fix it narrowly instead of turning
        the guardrail off.
      </p>

      <Steps>
        <Step title="Find the blocked run">
          <p>
            Open <strong>Traces</strong> and the run that was blocked. The run shows each check, what it
            found and why the call was stopped.
          </p>
          <Screenshot {...SCREENS.traceDetail} />
        </Step>

        <Step title="Mark the detection wrong">
          <p>
            On the run&apos;s <strong>Checks</strong> tab, press <strong>Wrong</strong> next to the
            detection. Press <strong>Correct</strong> on the ones that were right: a better threshold needs
            both. Marking changes nothing by itself.
          </p>
        </Step>

        <Step title="Lower the sensitivity, or add an exception">
          <p>
            <strong>For many similar cases</strong>, open the rule on <strong>Policies</strong>, press{" "}
            <strong>Change</strong>, and pick a lower <strong>Sensitivity</strong>. Choose{" "}
            <strong>Only some agents</strong> to change it for one agent.
          </p>
          <p>
            <strong>For one case</strong>, go to <strong>Settings → Detection → Detector tuning</strong>. Under{" "}
            <strong>Feedback</strong>, press <strong>Suppress 30 days</strong> on your mark. The exception
            covers that check and agent, and it expires.
          </p>
        </Step>

        <Step title="Check before you apply">
          <Tabs>
            <Tab label="In the app">
              <p>
                A sensitivity change is replayed against the agent&apos;s last 7 days before you press{" "}
                <strong>Apply</strong>. It says how many calls would be newly blocked or newly allowed. If the
                newly allowed ones include real attacks, use an exception instead.
              </p>
            </Tab>
            <Tab label="CLI">
              <p>Turn your marks into a proposed threshold, proven against the marked runs, then decide it.</p>
              <Code>{`agentfox policy proposals from-labels
agentfox policy proposals list
agentfox policy proposals show chp_…`}</Code>
            </Tab>
          </Tabs>
        </Step>
      </Steps>

      <Callout kind="tip">
        If no threshold separates the wrong detections from the right ones, the CLI says so. That calls for
        an exception, a stronger check, or an <Link href="/docs/reference/detectors">AI judge</Link>, not a dial.
      </Callout>

      <h2>Keep exceptions honest</h2>
      <ul>
        <li>Every exception expires. Detector tuning lists them with their hits and a <strong>Revoke</strong> button.</li>
        <li>An exception that is never used is marked <strong>Never used</strong>. Revoke it.</li>
        <li>Creating and revoking exceptions needs owner, admin or security. Marking a detection does not.</li>
      </ul>

      <h2>If something goes wrong</h2>
      <div className="docs-table"><table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>insufficient data</td>
            <td>Mark at least five detections for that check, wrong and correct together.</td>
          </tr>
          <tr>
            <td>Still blocked after an exception</td>
            <td>
              Another finding on the same message also met the rule. Mark and suppress that one too.
            </td>
          </tr>
          <tr>
            <td>Tool access refuses a call</td>
            <td>
              That is not a detector. Fix it on the agent&apos;s <Link href="/docs/govern">Access</Link>{" "}
              page.
            </td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/reference/detectors", label: "Detectors", why: "what each check finds and how to add one" },
          { href: "/docs/benchmarks", label: "Benchmarks", why: "how often the default checks are right" },
        ]}
      />
    </article>
  );
}
