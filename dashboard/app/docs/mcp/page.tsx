import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "MCP",
  description: "Scan a tool server, and catch the change a Monday scan cannot see.",
  path: "/docs/mcp",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>MCP</h1>
      <p>
        Approving a server once is not enough. A scan records the tools. The check that
        matters is at the call, against the digest that was in force when the agent was
        authorised.
      </p>
      <h2>Before anything runs</h2>
      <pre>
        <code>{`agentfox scan mcp
agentfox scan mcp fetch
agentfox scan mcp fetch --file tools.json
agentfox scan mcp --config ~/Library/Application\\ Support/Claude/claude_desktop_config.json`}</code>
      </pre>
      <p>
        With no setup, <code>scan mcp</code> reads the servers your MCP config declares
        (<code>.mcp.json</code>, <code>.cursor/mcp.json</code>,{" "}
        <code>.claude/settings.json</code>, <code>.claude.json</code> or{" "}
        <code>claude_desktop_config.json</code> in this directory, or the file{" "}
        <code>--config</code> names) and registers them. Nothing is started: it reports
        what each server can reach, whether its version is pinned, whether a remote one
        carries auth, and whether the config holds a literal credential. Servers loaded
        together that can read private data, read the web and send data out are
        flagged as a lethal trifecta.
      </p>
      <p>
        <code>--file</code> takes the server&apos;s real <code>tools/list</code> output
        and adds tool hygiene: a poisoned description, and schema drift since the last
        scan. <code>--seed-fixture</code> is the bundled example. An undeclared tool
        becomes a discovery finding rather than an invisible call.
      </p>
      <h2>At the call</h2>
      <p>
        The governor compares the tool&apos;s digest with the one recorded when the
        agent was authorised against it. That is the rug pull: a server that passed
        review on Monday and changed on Thursday, which no earlier scan can catch.
        Results are evaluated on the <code>tool_result</code> surface, and the taint is
        propagated, so an argument later derived from an MCP result cannot exceed the
        ceiling for tool-sourced data.
      </p>
      <p>
        The HTTP route for one MCP call is <code>POST /v1/mcp/call</code>. A read-only
        MCP server that exposes AgentFox itself to a coding agent is{" "}
        <code>agentfox serve mcp</code>, documented on the <Link href="/docs/harness">harness</Link>{" "}
        page. That server does not decide or apply a change.
      </p>
    </article>
  );
}
