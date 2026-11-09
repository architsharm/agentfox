import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { Tab, Tabs } from "@/components/docs/tabs";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Map your agents",
  description:
    "See every agent in your code, the models, tools and data it can reach, and which ones could be steered into sending data out. Rescan on every change and in CI.",
  path: "/docs/discover",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Map your agents</h1>
      <p className="docs-lede">
        See every agent in your code, what it can reach, and which ones need care first. Then keep the
        map current with rescans and a CI check.
      </p>

      <Steps topLevel>
        <Step title="Open the agent map">
          <p>
            Open <strong>Agents</strong>. Each agent is drawn with its user, its model, its tools and the
            documents it reads. Click any node or line for its details on the right.
          </p>
          <Screenshot {...SCREENS.agentMap} />
        </Step>

        <Step title="Read the lines and labels">
          <p>
            A line is a place where a guardrail can run: the user&apos;s message, the reply, a tool call, a
            tool&apos;s result. A line with our mark has guardrails on it; a <strong>+</strong> means none
            yet. Each tool carries its impact: <strong>Read only</strong>, <strong>Writes</strong>,{" "}
            <strong>High impact</strong> or <strong>Irreversible</strong>.
          </p>
        </Step>

        <Step title="Connect a GitHub repository">
          <p>
            In <strong>Settings → Connections</strong>, press <strong>Connect GitHub</strong>, then{" "}
            <strong>Scan</strong> next to a repository. The code is read, never run. New agents arrive on
            Agents as drafts until you add them.
          </p>
          <Screenshot {...SCREENS.sources} />
          <p>
            A scanned repository is rescanned every six hours. A new tool, a model call that lost its
            guardrails, or a new risky combination of tools becomes an Issue.
          </p>
        </Step>

        <Step title="Scan in CI">
          <Tabs>
            <Tab label="CLI">
              <p>
                Run the scan in any CI job. <code>--fail</code> fails the job when a model call has no
                guardrails. Nothing is sent anywhere.
              </p>
              <Code>{`pip install agentfox
agentfox scan --fail --no-submit`}</Code>
            </Tab>
            <Tab label="GitHub Action">
              <p>
                The AgentFox action comments on the lines that raised something and fails the check on a
                risky combination of tools or a poisoned skill.
              </p>
              <Code lang="yaml">{`- uses: actions/checkout@v4
- uses: architsharm/agentfox@main
  with:
    fail-on: trifecta,skills`}</Code>
            </Tab>
          </Tabs>
        </Step>
      </Steps>

      <h2 id="pattern">The pattern to fix first</h2>
      <p>
        An agent is at risk when it holds all three of these at once: a tool that reads{" "}
        <strong>private data</strong>, a tool that reads <strong>content an outsider can write</strong>{" "}
        (a web page, an email, an issue comment), and a tool that can <strong>send data out</strong>. An
        instruction hidden in that content can then make it send your data somewhere. The scan names
        the three tools and the fix. Usually the fix is to require approval on the tool that sends out (see{" "}
        <Link href="/docs/govern">Tool access</Link>).
      </p>

      <h2>What the scan reads</h2>
      <ul>
        <li>Python, TypeScript and JavaScript. Agents in the OpenAI and Anthropic SDKs, LangGraph, LangChain, CrewAI, AutoGen and Google ADK, and who hands work to whom.</li>
        <li>MCP servers from <code>.mcp.json</code>, Cursor, Claude Code and Claude Desktop configs.</li>
        <li>
          Not tools built at runtime, for example loaded from a database. Agents that send traffic show
          up anyway, marked unregistered.
        </li>
      </ul>

      <h2 id="monitoring">Keep re-checking connected sources (Enterprise)</h2>
      <p>
        A scan is a snapshot. With AgentFox Enterprise (Cloud, or the self-hosted Enterprise stack), a
        GitHub repository, a hosted API&apos;s OpenAPI document or an MCP server you connect in{" "}
        <strong>Settings → Connections</strong> is re-checked every few hours, and on every push once
        the GitHub webhook is registered. What changed since the last run becomes an issue (a new
        lethal trifecta, a model call that lost its governance, a new tool or destructive endpoint, an
        MCP server whose tools drifted), and the issue closes itself when the condition clears.
        <strong> Settings → Alerts</strong> lists what is watched, with <strong>Run now</strong> and{" "}
        <strong>Pause</strong>.
      </p>
      <Code>{`agentfox scan monitors list                      # what is watched, last outcome, next run
agentfox scan monitors add github_repo acme/bot  # or created for you when you connect one
agentfox admin jobs run-due                      # self-hosted: put this on cron`}</Code>
      <p>
        With the open-source package alone, <code>agentfox scan monitors</code> says it is not
        installed. Run the scan on every pull request instead, with the GitHub Action above.
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
            <td>The scan proposes nothing</td>
            <td>
              The agent sits behind a wrapper the scan does not know. Connect it with{" "}
              <Link href="/docs/connect/python">one line in Python</Link> instead.
            </td>
          </tr>
          <tr>
            <td>A tool has the wrong impact</td>
            <td>Change it on the agent&apos;s <strong>Access</strong> page. Your choice always wins over the guess.</td>
          </tr>
          <tr>
            <td>Connecting GitHub fails with 503</td>
            <td>
              A self-hosted gateway needs <code>AGENTFOX_TOKEN_ENCRYPTION_KEY</code> to store the GitHub
              token.
            </td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "limit what each agent may call" },
          { href: "/docs/connect/mcp", label: "MCP servers", why: "pin and check the servers the scan found" },
          { href: "/docs/reference/cli#cmd-scan-repo", label: "agentfox scan reference", why: "JSON output, skills, MCP, runtime" },
        ]}
      />
    </article>
  );
}
