import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Control point commands",
  description: "The same rules at the hook, the gateway, the SDK, LangGraph, and the CLI.",
  path: "/docs/control-points",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>Control points</h1>
      <p>
        Six places. Each one calls the same enforcer and writes the same decision
        record. What changes is the surface it can see, so connecting one does not
        cover the others. The calls themselves are on{" "}
        <Link href="/docs/connect">Where it connects</Link>.
      </p>
      <h2>Coding agent</h2>
      <pre>
        <code>agentfox admin hooks install --agent my-agent --write</code>
      </pre>
      <h2>Any language</h2>
      <pre>
        <code>agentfox serve</code>
      </pre>
      <h2>Python</h2>
      <pre>
        <code>import agentfox; agentfox.auto()</code>
      </pre>
      <h2>Tool servers</h2>
      <pre>
        <code>agentfox scan mcp</code>
      </pre>
      <h2>LangGraph</h2>
      <pre>
        <code>{`guard.tool_node(transfer, tool="payments.transfer")`}</code>
      </pre>
      <h2>CI and the terminal</h2>
      <pre>
        <code>agentfox scan --sessions .</code>
      </pre>
      <h2>The policy</h2>
      <pre>
        <code>{`agentfox policy lint
agentfox policy observe baseline`}</code>
      </pre>
      <p>A rule written for the gateway is already in force at the hook. Observe records the verdict and changes nothing until you promote it.</p>
    </article>
  );
}
