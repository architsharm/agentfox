/**
 * /mcp — MCP governance.
 *
 * Same template as the other seven product pages; what is only true here is
 * the six-risk table, so that is the `feature`. Two of the six are gaps and
 * they are drawn as gaps, because a table that styled all six alike would
 * read as six wins.
 */

import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "MCP security: tool poisoning and rug pulls",
  description:
    "Approving an MCP server once is not enough. If a tool changes later, that shows up when it is called.",
  path: "/mcp",
});

const RISKS = [
  {
    risk: "Tool drift, or the rug pull",
    what: "A server passes review, an agent is authorised against it, and the tool's schema or description changes afterwards.",
    us: "Checked at call time",
    covered: true,
    how: "The digest from when the agent was authorised is compared with the digest at the call.",
  },
  {
    risk: "Tool poisoning",
    what: "A manipulated tool description steers the agent into leaking data or taking an action nobody asked for.",
    us: "Covered",
    covered: true,
    how: "Descriptions are scanned. Changing one is also drift.",
  },
  {
    risk: "A poisoned result",
    what: "Content authored by a third party arrives as trusted context through a tool the agent was allowed to call.",
    us: "Covered",
    covered: true,
    how: "What comes back is treated as untrusted, and that follows any argument derived from it.",
  },
  {
    risk: "An undeclared tool",
    what: "The agent calls a tool nobody registered. Hygiene scanning never sees it, because nobody pointed a scan at that server.",
    us: "Becomes a finding",
    covered: true,
    how: "The first call is still the first call. It becomes a finding, not an invisible one.",
  },
  {
    risk: "An over-scoped server",
    what: "One server can read sensitive data or trigger destructive actions far beyond what the agent using it needs.",
    us: "Partly",
    covered: false,
    how: "A single call can be bounded. We do not yet say the server can do far more than this agent has needed.",
  },
  {
    risk: "Credential sprawl",
    what: "Every agent holds its own upstream credentials, multiplying the blast radius of any one leak.",
    us: "Not covered",
    covered: false,
    how: "We do not hold or consolidate upstream credentials.",
  },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="MCP security"
      title={["Tool poisoning", "and rug pulls"]}
      lede="Approving the server once is not enough. If a tool changes later, that shows up when it is called."
      docs="/docs/mcp"
      challenge={
        <p>You review a server once. The agent calls it for months.</p>
      }
      feature={{
        title: "Six risks, and the two we miss",
        lede: "Two of them are not covered.",
        body: (
          <div className="mcp-risks mk-stagger">
            {RISKS.map((row) => (
              <article
                key={row.risk}
                className={row.covered ? "mcp-risk" : "mcp-risk mcp-risk-gap"}
              >
                <div className="mcp-risk-head">
                  <h3>{row.risk}</h3>
                  <span className={row.covered ? "mcp-chip mcp-chip-on" : "mcp-chip"}>
                    {row.us}
                  </span>
                </div>
                <p className="mcp-what">{row.what}</p>
                <p className="mcp-how">{row.how}</p>
              </article>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "A Monday scan says nothing about Thursday",
          body: <p>The comparison happens when the tool is called, against the digest from when the agent was authorised.</p>,
        },
        {
          title: "The client does not matter",
          body: <p>Official SDK, a hand-rolled client, or the gateway. The mcp package is not a dependency of ours.</p>,
        },
      ]}
      gaps={{
        title: "The two we do not cover",
        body: (
          <p>
            We cannot yet say a server can do far more than this agent has needed. And
            we do not hold upstream credentials, so we cannot consolidate them.
          </p>
        ) }}
      related={["/hooks", "/grants", "/discovery"]}
    />
  );
}
