import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Discovery",
  description: "Scan a repository, a laptop session, and the agents that registered themselves.",
  path: "/docs/discovery",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>Discovery</h1>
      <p>
        An inventory before an opinion. The scans read. They do not run your code, and
        a scan that understood none of the files says so rather than reporting clean.
      </p>

      <h2>A repository</h2>
      <pre>
        <code>agentfox check</code>
      </pre>
      <p>
        From the project directory. It reports what the code is built on, how many
        model call sites are ungoverned, every tool and MCP server the agent can reach,
        and what else it found: agent definitions, secrets, shell calls, and SQL built
        near model output. It writes nothing to the project and sends nothing anywhere.
      </p>
      <p>
        Tools are found however they are declared: decorated functions, OpenAI function
        schemas passed as <code>tools=</code> (inline or through a list built
        elsewhere), and Anthropic tool dicts with <code>name</code> and{" "}
        <code>input_schema</code>. MCP servers come from <code>.mcp.json</code>,{" "}
        <code>.cursor/mcp.json</code>, <code>.claude.json</code>,{" "}
        <code>.claude/settings.json</code> and <code>claude_desktop_config.json</code>.
      </p>

      <h3>The lethal trifecta</h3>
      <p>
        Each tool and server is classified by what it can do: read private data, read
        content someone outside can write, or send data out and act irreversibly. When
        one agent has all three, an instruction hidden in a web page or an email can
        make it send your data somewhere. That is printed first, as a sentence:
      </p>
      <pre>
        <code>{`bot.py: can read customer records (read_customer_record), reads untrusted
web pages (fetch_url), and can send email (send_email). An instruction hidden
in a web page could send customer data out.`}</code>
      </pre>
      <p>
        with the command that contains it: a capability grant that makes anything
        derived from untrusted content wait for approval before it reaches the send
        tool, or <code>agentfox.auto(mode=&quot;observe&quot;)</code> to watch it happen
        first. Tools in code are grouped by directory; MCP servers by the config file
        that loads them into one client. The classification reads names and
        descriptions, so a tool whose name says nothing is left unflagged, and an MCP
        server AgentFox does not recognise is reported as unknown, never as safe.
      </p>

      <h2>This machine, including sessions that were never committed</h2>
      <pre>
        <code>agentfox quickscan</code>
      </pre>
      <p>
        The same static look, plus local AI-tool session transcripts, plus a handful of
        known-adversarial prompts run through the detector pipeline in the terminal so
        you can watch a catch happen. Nothing leaves the machine. A one-off of the same
        idea, from a virtualenv the script deletes on exit, is the{" "}
        <code>quickscan.sh</code> line on <Link href="/docs">Getting started</Link>.
      </p>

      <h2>Agents, including ones nobody registered</h2>
      <pre>
        <code>{`agentfox agents list
agentfox agents discover
agentfox agents lineage payments-ops`}</code>
      </pre>
      <p>
        <code>agents list</code> prints every agent, its environment, risk, whether it
        is registered or shadow, and who owns it. A call to the gateway for an agent
        that does not exist yet registers that agent as shadow traffic, unowned, and{" "}
        <code>agentfox findings</code> shows the matching <code>shadow_agent</code>{" "}
        finding. <code>agents discover</code> sweeps for shadow agents, drift, and
        identity posture. <code>agents lineage</code> is what one agent can reach: its
        blast radius.
      </p>
      <p>
        An agent with no owner is a finding. Tool servers are a separate scan, on{" "}
        <Link href="/docs/mcp">MCP</Link>.
      </p>
    </article>
  );
}
