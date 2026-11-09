import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Claude Code and Codex",
  description:
    "Install AgentFox as Claude Code or Codex hooks so prompts, tool calls and tool results are checked on your machine, and add the operator plugin.",
  path: "/docs/connect/coding-agents",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Claude Code and Codex</h1>
      <p className="docs-lede">
        Check every prompt, tool call and tool result in a Claude Code or Codex session on your
        machine, and refuse destructive or credential-reading commands before they run.
      </p>

      <h2>Before you start</h2>
      <ul>
        <li>
          <code>agentfox</code> is installed and on the PATH your coding agent runs hooks with.
        </li>
      </ul>

      <Steps>
        <Step title="Install the hooks">
          <p>
            Without <code>--write</code> it only prints the config. With it, it writes{" "}
            <code>.claude/settings.json</code>, registers the agent, and grants Claude Code&apos;s
            built-in tools so ordinary work is not refused.
          </p>
          <Code>{`agentfox admin hooks install --agent claude-dev --write`}</Code>
        </Step>

        <Step title="Run init again">
          <p>
            This turns on the <code>coding-agent</code> rules for the agent the hooks govern. They start
            in Watch.
          </p>
          <Code>{`agentfox init`}</Code>
        </Step>

        <Step title="Start the daemon">
          <p>
            Each hook asks a background process, so a check takes milliseconds. Keep it running in a
            terminal tab or under your process manager, then check it is listening.
          </p>
          <Code>{`agentfox admin hooks daemon
agentfox admin hooks status`}</Code>
        </Step>

        <Step title="Grant the other tools your sessions use">
          <p>
            MCP tools arrive as <code>mcp__server__tool</code> and have no grant, so they are refused.
            Grant one, or let a few sessions run and have grants proposed from what the agent called.
          </p>
          <Code>{`agentfox permit grant claude-dev mcp__github__create_issue
agentfox policy proposals from-traffic --agent claude-dev`}</Code>
        </Step>

        <Step title="Switch to Block">
          <p>
            After a few days, read what the <code>coding-agent</code> rules would have stopped on the{" "}
            <strong>Issues</strong> page, then turn them on.
          </p>
          <Code>{`agentfox policy enforce coding-agent`}</Code>
        </Step>
      </Steps>

      <h2>What is refused from the start</h2>
      <p>The shell rules block from day one, whatever the grants say:</p>
      <div className="docs-table"><table>
        <thead>
          <tr>
            <th>Command</th>
            <th>Rule</th>
          </tr>
        </thead>
        <tbody>
          <tr><td><code>curl … | sh</code></td><td><code>action.remote_code_execution</code></td></tr>
          <tr><td><code>cat .env</code>, <code>cat ~/.aws/credentials</code></td><td><code>secrets.credential_file</code></td></tr>
          <tr><td><code>rm -rf ~</code></td><td><code>shell.destructive</code></td></tr>
          <tr><td><code>git reset --hard HEAD~3</code></td><td><code>action.history_rewrite</code></td></tr>
          <tr><td><code>terraform apply</code>, <code>npm publish</code></td><td><code>action.infrastructure_mutation</code>, <code>action.supply_chain_publish</code></td></tr>
          <tr><td>Turning AgentFox off, e.g. <code>agentfox policy observe …</code></td><td><code>control_plane.tamper</code></td></tr>
        </tbody>
      </table></div>
      <p>
        A refused tool call does not run, and the agent is told which rule stopped it. A refused prompt
        never reaches the model. A tool result cannot be undone; when it carries injected instructions,
        the agent is told to treat it as data.
      </p>

      <Callout kind="warning" title="If the daemon is down, nothing is checked">
        <p>
          The hook allows the call and prints a warning on stderr. Run{" "}
          <code>agentfox admin hooks status</code> before you rely on it.
        </p>
      </Callout>

      <h2 id="codex">Codex</h2>
      <p>The same steps, with three differences:</p>
      <ol>
        <li>
          Install with <code>--harness codex</code>. It writes <code>.codex/hooks.json</code>; add{" "}
          <code>--scope user</code> for <code>~/.codex/hooks.json</code> and every project.
        </li>
        <li>
          Open Codex in the project, run <code>/hooks</code> and trust the three AgentFox hooks. Codex
          skips a hook nobody trusted, and a changed file needs trusting again.
        </li>
        <li>
          Codex cannot ask you from a hook, so a call that needs a person is refused with the reason.
          Hosted tools such as web search run on OpenAI&apos;s side and are not checked.
        </li>
      </ol>
      <Code>{`agentfox admin hooks install --harness codex --agent codex-dev --write`}</Code>

      <h2 id="plugin">The operator plugin</h2>
      <p>
        Separate from the hooks, the AgentFox plugin lets Claude Code drive AgentFox for you: slash
        commands such as <code>/agentfox:tour</code>, <code>/agentfox:start</code>,{" "}
        <code>/agentfox:status</code> and <code>/agentfox:redteam</code>, matching skills, and the
        read-only <Link href="/docs/connect/mcp">AgentFox MCP server</Link>. It asks you before any
        command that changes what is blocked or granted.
      </p>
      <Code>{`claude plugin marketplace add architsharm/agentfox
claude plugin install agentfox@agentfox`}</Code>
      <p>
        For Codex: <code>codex plugin marketplace add architsharm/agentfox</code>, then{" "}
        <code>codex plugin add agentfox@agentfox</code>. The Codex plugin refuses those commands and
        tells the agent to hand them to you.
      </p>

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
            <td>A tool refused with <code>capability.denied</code></td>
            <td>It is not a built-in tool. Grant it with <code>agentfox permit grant</code>.</td>
          </tr>
          <tr>
            <td>AF_UNIX path too long</td>
            <td>Set <code>AGENTFOX_STATE_DIR</code> to a shorter folder, for the daemon and the coding agent.</td>
          </tr>
          <tr>
            <td>coding-agent not enabled, from init</td>
            <td>Install the hooks first, then run <code>agentfox init</code> again.</td>
          </tr>
          <tr>
            <td>Codex runs everything unchecked</td>
            <td>Trust the hooks in <code>/hooks</code>, and start the daemon.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/connect/mcp", label: "MCP servers", why: "scan the servers your sessions load" },
          { href: "/docs/reference/cli#cmd-admin-hooks-install", label: "agentfox admin hooks", why: "every flag" },
        ]}
      />
    </article>
  );
}
