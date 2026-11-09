import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Traces and issues",
  description:
    "Find a run, see every check it went through and why it was blocked, mark a check right or wrong, and work the Issues queue.",
  path: "/docs/prove",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Traces and issues</h1>
      <p className="docs-lede">
        Find out why a call was blocked, tell AgentFox when a check was wrong, and clear the issues
        that need a person.
      </p>

      <Steps topLevel>
        <Step title="Find the run">
          <p>
            Open <strong>Traces</strong>. The <strong>Runs</strong> tab lists recent runs with their
            agent and outcome. Filter by <strong>Blocked</strong>, <strong>Held</strong>,{" "}
            <strong>Masked</strong> or <strong>Errors</strong>, or by agent. To jump to one, press ⌘K
            and paste its id (<code>trc_…</code>).
          </p>
          <Screenshot {...SCREENS.traces} />
        </Step>

        <Step title="See why it was blocked">
          <p>
            Open the run. <strong>Summary</strong> says what decided it, which rule, and what to do.{" "}
            <strong>Steps</strong> shows each model and tool call in order, <strong>Checks</strong>{" "}
            every check with its score, and <strong>Data origin</strong> where each tool argument
            came from (the user, a document, another tool).
          </p>
          <Screenshot {...SCREENS.traceDetail} />
        </Step>

        <Step title="Mark a check right or wrong">
          <p>
            On a check that found something, press <strong>Correct</strong> or <strong>Wrong</strong>.
            A label changes nothing on its own: it feeds{" "}
            <Link href="/docs/protect/tuning">Fix false positives</Link>, where a wrong catch is one
            click from a scoped, expiring exception.
          </p>
        </Step>

        <Step title="Work the Issues queue">
          <p>
            <strong>Issues</strong> lists what needs a person: a guardrail catch, a refused tool call,
            an agent nobody registered, an attack that got through. A problem that keeps happening is
            one row with a count.
          </p>
          <Screenshot {...SCREENS.issues} />
        </Step>

        <Step title="Resolve or accept">
          <p>
            Open an issue to see its evidence. <strong>Mark resolved</strong> needs a note on what
            fixed it. <strong>Accept</strong> needs a reason, and keeps the issue visible under{" "}
            <strong>Accepted</strong> instead of looking fixed.
          </p>
        </Step>
      </Steps>

      <h2>Reading an issue title</h2>
      <ul>
        <li>
          <strong>(contained)</strong> or <strong>(held for approval)</strong>: the rule blocks, and
          the call was stopped or sent to <Link href="/docs/govern/approvals">Approvals</Link>.
        </li>
        <li>
          <strong>(would have been contained)</strong> or <strong>Would have been blocked on …</strong>:
          the rule is in Watch. The call went through; the issue shows what Block would change.
        </li>
        <li>
          <code>critical</code> means look today, <code>high</code> this week. The rule or check that
          raised it sets the severity.
        </li>
      </ul>

      <h2>From the command line</h2>
      <p>
        The CLI calls issues findings. The same queue, worst first:
      </p>
      <Code>{`agentfox findings --severity high`}</Code>
      <p>
        Resolving and accepting are in the app, or <code>PATCH /api/findings/&#123;id&#125;</code>.
        Traces are listed in the app or with <code>GET /api/traces</code>; there is no CLI command for
        them. Every issue type is in <Link href="/docs/reference/detectors#finding-types">Detectors
        and findings</Link>.
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
            <td>A run says nothing was checked</td>
            <td>
              No governed step ran on that turn. Check prompts as well as tool calls; see{" "}
              <Link href="/docs/connect/python">Python apps</Link>.
            </td>
          </tr>
          <tr>
            <td>A resolved issue comes back</td>
            <td>The problem happened again. Resolving records a fix; it does not turn the check off.</td>
          </tr>
          <tr>
            <td>Masked text you cannot read</td>
            <td>By design. Values are masked when recorded and the original is not stored.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/prove/audit", label: "Audit evidence", why: "turn the record into something an auditor can check" },
          { href: "/docs/prove/integrations", label: "Send traces elsewhere", why: "Langfuse, LangSmith, your SIEM, a webhook" },
        ]}
      />
    </article>
  );
}
