import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "MCP servers",
  description:
    "Check the MCP servers your agents load, pin their versions, catch tool changes, and grant each MCP tool like any other tool.",
  path: "/docs/connect/mcp",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>MCP servers</h1>
      <p className="docs-lede">
        Check every MCP server your agents load, notice when a server&apos;s tools change, and let
        each agent call only the MCP tools you grant it.
      </p>

      <Steps topLevel>
        <Step title="Scan the servers in your repository">
          <p>
            Run this where your MCP config lives (<code>.mcp.json</code>, <code>.cursor/mcp.json</code>,{" "}
            <code>.claude/settings.json</code>, <code>claude_desktop_config.json</code> and similar). It
            starts no server.
          </p>
          <Code>{`agentfox scan mcp`}</Code>
          <p>
            For each server you see what it can reach, a version that is not pinned, a token written
            into <code>env</code>, and a remote server with no auth. Use <code>--config</code> to read a
            file somewhere else.
          </p>
        </Step>

        <Step title="Scan the servers on your machine">
          <p>
            Most servers are added once to an AI tool, not committed. This reads the user-level configs
            of Claude Code, Claude Desktop, Cursor, Windsurf, VS Code, Cline, Gemini CLI and Codex, plus
            installed skills. It writes nothing and never prints an <code>env</code> value.
          </p>
          <Code>{`agentfox scan machine`}</Code>
        </Step>

        <Step title="Pin each server's version">
          <p>
            A server started with <code>npx</code>, <code>uvx</code> or <code>docker</code> and no version
            runs whatever is newest, so its tools can change after you reviewed them. Pin it in the
            config: <code>@modelcontextprotocol/server-github@2025.4.8</code>,{" "}
            <code>mcp-server-fetch==2025.4.7</code>, or an image tag other than <code>latest</code>. Write
            secrets as <code>{"${GITHUB_TOKEN}"}</code>, not the value.
          </p>
        </Step>

        <Step title="Record each server's tools">
          <p>
            Save the server&apos;s <code>tools/list</code> response to a file and scan it. Each scan keeps a
            snapshot, so the next one reports <strong>tools changed since the last scan</strong> and any
            instructions hidden in a tool description.
          </p>
          <Code>{`agentfox scan mcp github --file github-tools.json`}</Code>
        </Step>

        <Step title="Grant the tools each agent may call">
          <p>
            MCP tools are named <code>mcp:&lt;server&gt;/&lt;tool&gt;</code>, so two servers&apos;{" "}
            <code>search</code> tools stay apart. A tool nobody granted is refused.
          </p>
          <Code>{`agentfox permit grant research-bot mcp:github/search_issues`}</Code>
          <p>
            Grant a whole server with <code>mcp:github/*</code> only if every tool on it should be
            callable. You can also grant from the agent&apos;s <strong>Access</strong> tab; see{" "}
            <Link href="/docs/govern">Tool access</Link>.
          </p>
        </Step>
      </Steps>

      <h2>How calls get checked</h2>
      <ul>
        <li>
          <strong>Python:</strong> wrap your MCP client&apos;s <code>call_tool</code> in{" "}
          <code>McpGovernor</code> (<Link href="/docs/reference/python">Python SDK</Link>). Each call is
          checked before it runs and its result after.
        </li>
        <li>
          <strong>Any language:</strong> call <code>POST /v1/guard/tool_call</code> with the tool{" "}
          <code>mcp:&lt;server&gt;/&lt;tool&gt;</code> before you call the server, then send the result to{" "}
          <code>POST /v1/mcp/call</code> to have it checked. See{" "}
          <Link href="/docs/connect/http">Any language (HTTP)</Link>.
        </li>
        <li>
          <strong>Claude Code and Codex:</strong> the hooks check MCP tools like any other tool. See{" "}
          <Link href="/docs/connect/coding-agents">Claude Code and Codex</Link>.
        </li>
      </ul>

      <Callout kind="note" title="When a server's tools change">
        <p>
          If a tool&apos;s name, description, input schema or impact hints change after it was
          registered, its calls are refused with <code>mcp.schema_drift</code> and an issue is raised.
          Accepting the change unblocks it for every agent, so it needs two different people to approve.
        </p>
      </Callout>

      <h2>Give an AI client read-only access to AgentFox</h2>
      <p>
        <code>agentfox serve mcp</code> serves AgentFox over MCP stdio: issues, agents, policies,
        simulations and checks. None of its tools changes what is blocked. Add it to your client&apos;s
        config as <code>{`{"command": "agentfox", "args": ["serve", "mcp"]}`}</code>. The{" "}
        <Link href="/docs/connect/coding-agents#plugin">Claude Code plugin</Link> starts it for you.
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
            <td>No MCP servers declared in this directory</td>
            <td>Run from the folder with the config, or pass <code>--config</code>.</td>
          </tr>
          <tr>
            <td>name the server the tool list belongs to</td>
            <td><code>--file</code> needs the server name too: <code>scan mcp github --file …</code>.</td>
          </tr>
          <tr>
            <td>Every call to one server refused with <code>mcp.schema_drift</code></td>
            <td>The server changed. Review it, then have two people accept the change.</td>
          </tr>
          <tr>
            <td>unknown agent on <code>permit grant</code></td>
            <td>Run the agent once so it registers, then grant.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "grants, limits and approvals for mcp: tools" },
          { href: "/docs/reference/cli#cmd-scan-mcp", label: "agentfox scan mcp", why: "every flag and exit code" },
        ]}
      />
    </article>
  );
}
