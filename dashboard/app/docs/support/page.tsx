import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { Callout, Code, NextSteps } from "@/components/docs/blocks";
import { REPO_URL, publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Troubleshooting",
  description:
    "Common AgentFox problems and their fixes, what to do when an agent misbehaves, and how to file an issue without leaking secrets.",
  path: "/docs/support",
});

const PROBLEMS: [ReactNode, ReactNode][] = [
  ["init says no agent found", <>Run <code>agentfox init</code> in the repository where the agent is defined.</>],
  ["No such option: --key", <>Upgrade: <code>pip install -U agentfox</code>.</>],
  ["Nothing appears on Activity", <>Start the app from the folder where <code>init</code> ran, or set <Link href="/docs/connect/python#key">the two environment variables</Link>.</>],
  ["The attack test never starts", <>Keep <code>agentfox init</code> running. It runs the attacks on your machine.</>],
  ["A real user gets blocked", <>Open the run on <strong>Activity</strong>, press <strong>Wrong</strong> on the check, then follow <Link href="/docs/protect/tuning">Fix false positives</Link>.</>],
  ["An attack is flagged but not stopped", <>The guardrail is in Watch. <Link href="/docs/protect">Switch it to Block</Link>.</>],
  ["A tool call is refused for no clear reason", <>The agent was not given that tool. Check its <strong>Access</strong> tab, or <code>agentfox permit list</code>.</>],
  ["A detector you turned on never fires", <>Its extra or model weights are missing. <code>agentfox admin detectors list</code> says what it needs.</>],
  ["Webhooks, Slack or a hosted model do nothing", <>Set <code>AGENTFOX_ALLOW_EGRESS=true</code>. With egress off nothing leaves the server.</>],
  ["API calls return 401", <>The server requires tokens. Send <code>Authorization: Bearer nom_api_…</code>; <code>agentfox admin auth status</code> says which mode is on.</>],
  [<>CI says <code>unknown suite</code></>, <><code>AGENTFOX_DATABASE_URL</code> points at a different database from the one with the suite.</>],
  ["Compliance counts are all zero (Enterprise)", <>Press <strong>Load control catalog</strong> on Reports → Compliance, or run <code>agentfox admin catalog sync</code>. Without AgentFox Enterprise there is no compliance view; the open core has <code>agentfox report</code> and <code>agentfox report verify</code>.</>],
  ["The audit log check fails", <>An entry was changed or removed after it was written. <code>agentfox report verify</code> names the first broken entry.</>],
  ["agentfox up edited my file and I want it back", <><code>up</code> adds two lines to the entry point: <code>import agentfox</code> and <code>agentfox.auto(…)</code>, marked <code># added by `agentfox up`</code>. Delete them, or restore the file from version control. Everything else it wrote is listed under <Link href="/docs/reference/install#uninstall">Uninstall</Link>.</>],
  [<>Every run prints <code>AgentFox is governing …</code></>, <>That banner on stderr is <code>auto()</code> saying what it covers. <code>agentfox.auto(quiet=True)</code> hides it; <code>AGENTFOX_VERBOSE=1</code> prints the full account.</>],
  ["I want AgentFox off for a while", <>Set <code>AGENTFOX_DISABLED=1</code> and restart the app. See <Link href="/docs/reference/install#turn-off">Turn it off</Link>.</>],
];

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Troubleshooting</h1>
      <p className="docs-lede">
        Fix the common problems, stop an agent that is misbehaving, and get help when neither works.
      </p>

      <h2>Start with doctor</h2>
      <p>
        <code>agentfox doctor</code> checks the setup: database, detectors, keys, modes, egress. It
        says what is wrong and what to change.
      </p>
      <Code>{`agentfox doctor`}</Code>

      <h2>Common problems</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          {PROBLEMS.map(([problem, fix], i) => (
            <tr key={i}>
              <td>{problem}</td>
              <td>{fix}</td>
            </tr>
          ))}
        </tbody>
      </table></div>

      <h2 id="faq">Questions people ask</h2>
      <dl className="docs-faq">
        <dt>Does AgentFox block my users from the start?</dt>
        <dd>
          No. Checks start in Watch: they record what they would have stopped. What is refused
          from the start is a destructive command or statement, an agent you paused, and, once an
          agent holds any grant, a tool it was not given. You switch a guardrail to Block when its
          results look right.
        </dd>
        <dt>Does my traffic leave my machine?</dt>
        <dd>
          Not to AgentFox without a key. With one, <code>auto()</code> sends each check to your
          account: <Link href="/docs/connect/python#what-is-sent">exactly what is sent</Link>.
        </dd>
        <dt>Do I need a database or a server?</dt>
        <dd>
          No. Without an account, the CLI and <code>auto()</code> use one SQLite file per
          installation, created on first use (
          <Link href="/docs/reference/install#state">where it lives</Link>). Postgres and{" "}
          <code>agentfox serve</code> are for a shared, self-hosted deployment.
        </dd>
        <dt>Do I need a database in CI?</dt>
        <dd>
          No. <code>agentfox scan --fail</code> and the{" "}
          <Link href="/docs/test/ci">GitHub Action</Link> read the repository and write nothing.
          Commands that keep state create a SQLite file on first use; point{" "}
          <code>AGENTFOX_STATE_DIR</code> at a temporary folder so each run starts clean.
        </dd>
        <dt>How do I turn it off, or remove it?</dt>
        <dd>
          <code>AGENTFOX_DISABLED=1</code> turns <code>auto()</code> off without a code change.{" "}
          <Link href="/docs/reference/install#uninstall">Uninstall</Link> lists every file AgentFox
          writes and how to revoke your key.
        </dd>
        <dt>Which commands need AgentFox Enterprise?</dt>
        <dd>
          Compliance, evidence packages and monitoring of connected sources. They are marked{" "}
          <strong>Enterprise</strong> in the <Link href="/docs/reference/cli">CLI reference</Link>,
          and the open-source package says so if you run one.
        </dd>
        <dt>The app says Issues, the CLI says findings. Same thing?</dt>
        <dd>
          Yes. The <Link href="/docs/concepts#glossary">glossary</Link> maps each name in the app
          to the CLI&apos;s.
        </dd>
      </dl>

      <h2 id="incident">When an agent misbehaves</h2>
      <ol>
        <li>
          Stop it: <strong>Stop</strong> in the agent&apos;s status menu, or{" "}
          <code>agentfox agents kill support-triage</code> (use your agent&apos;s name;{" "}
          <code>agentfox agents list</code> shows them). Every call it makes is refused until you
          resume it.
        </li>
        <li>Deny its calls waiting on <strong>Approvals</strong>.</li>
        <li>
          See what it can reach: <code>agentfox agents lineage support-triage</code>.
        </li>
        <li>Read its recent runs on <strong>Activity</strong>.</li>
        <li>
          Withdraw the tool that was misused on its <strong>Access</strong> tab, or with{" "}
          <code>agentfox permit revoke</code> and the grant id from <code>agentfox permit list</code>.
        </li>
        <li>
          Resume it (<code>agentfox agents resume support-triage</code>) and check the audit log is
          intact: <code>agentfox report verify</code>.
        </li>
      </ol>

      <h2>Get help</h2>
      <p>
        File bugs and questions on <a href={`${REPO_URL}/issues`}>GitHub issues</a>. Include the
        output of <code>agentfox doctor</code> and <code>agentfox admin version</code>, the verdict
        and rules that fired, and the smallest example that shows the problem, with made-up values.
        Report a security vulnerability through GitHub&apos;s private security advisories, never in a
        public issue. More ways to reach us are on <Link href="/support">Support</Link>.
      </p>
      <Callout kind="warning" title="A GitHub issue is public">
        Never paste API tokens (<code>nom_api_…</code>), provider keys, signing or encryption keys,
        a database URL with a password, real prompts, tool arguments or customer data, or rows from
        the audit log or an evidence package. Replace names and emails with placeholders such as{" "}
        <code>ada@example.com</code>.
      </Callout>

      <NextSteps
        items={[
          { href: "/docs/protect/tuning", label: "Fix false positives", why: "when a guardrail blocks a real user" },
          { href: "/docs/reference/install#uninstall", label: "Uninstall", why: "every file AgentFox writes" },
          { href: "/docs/concepts#glossary", label: "Glossary", why: "the app's names and the CLI's" },
        ]}
      />
    </article>
  );
}
