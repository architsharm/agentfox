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
    how: "The digest in force when the agent was authorised is compared against the digest at the moment of the call. A scan on Monday says nothing about a call on Thursday; only a check at the call can.",
  },
  {
    risk: "Tool poisoning",
    what: "A manipulated tool description steers the agent into leaking data or taking an action nobody asked for.",
    us: "Covered",
    covered: true,
    how: "Descriptions are scanned, and the description is part of the digest above — so poisoning an approved tool is also drift.",
  },
  {
    risk: "A poisoned result",
    what: "Content authored by a third party arrives as trusted context through a tool the agent was allowed to call.",
    us: "Covered",
    covered: true,
    how: "Results are evaluated on the tool_result surface and the taint is propagated, so an argument later derived from that text cannot exceed the ceiling for tool-sourced data.",
  },
  {
    risk: "An undeclared tool",
    what: "The agent calls a tool nobody registered. Hygiene scanning never sees it, because nobody pointed a scan at that server.",
    us: "Becomes a finding",
    covered: true,
    how: "It is recorded as an observed tool and raised as a discovery finding — visible rather than invisible. The first call is still the first call, and we do not pretend otherwise.",
  },
  {
    risk: "An over-scoped server",
    what: "One server can read sensitive data or trigger destructive actions far beyond what the agent using it needs.",
    us: "Partly",
    covered: false,
    how: "Impact inference and the capability ceiling bound what any single call can do. What we do not yet say is 'this server can do far more than this agent has ever needed', which is the posture finding worth having.",
  },
  {
    risk: "Credential sprawl",
    what: "Every agent holds its own upstream credentials, multiplying the blast radius of any one leak.",
    us: "Not covered",
    covered: false,
    how: "We do not broker or hold upstream credentials, so we cannot consolidate them. Listed because it is a real MCP risk and leaving it out would make this table a sales sheet.",
  },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="MCP security"
      title={["Tool poisoning", "and rug pulls"]}
      lede="Approving the server once is not enough. If a tool changes later, that shows up when it is called. Two risks on this page are not covered."
      docs="/docs/mcp"
      challenge={
        <p>
          MCP is how agents reach tools, and every server is somebody else&rsquo;s code.
          You review it once. The agent calls it for months.
        </p>
      }
      feature={{
        title: "Six risks, and the two we miss",
        lede: "Scored against the six risks the rest of this market lists.",
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
          title: "Snapshot the tools, with a digest",
          body: (
            <p>
              Every server&rsquo;s tools are recorded when it is scanned, description
              and schema included. That digest is what makes a later change detectable
              at all.
            </p>
          ),
        },
        {
          title: "Compare at the call, not at the scan",
          body: (
            <p>
              The digest in force when the agent was authorised is checked against the
              digest at the moment of the call. A scan on Monday says nothing about a
              call on Thursday.
            </p>
          ),
        },
        {
          title: "Treat what comes back as untrusted",
          body: (
            <p>
              Results are evaluated on the <code>tool_result</code> surface with the
              taint propagated, so an argument later derived from that text cannot
              exceed the ceiling for tool-sourced data.
            </p>
          ),
        },
        {
          title: "It does not matter how the tool server is connected",
          body: (
            <p>
              The governor wraps any callable that speaks list-tools and call-tool, so
              it works with the official SDK, a hand-rolled client or the
              gateway&rsquo;s proxy route — and the <code>mcp</code> package is never a
              dependency of ours.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "The two we do not cover",
        body: (
          <p>
            We cannot say &ldquo;this server can do far more than this agent has ever
            needed&rdquo;, which is the over-scope finding worth having. And we do not
            broker upstream credentials, so we cannot consolidate them — credential
            sprawl is a real MCP risk and one we leave where it is.
          </p>
        ) }}
      related={["/hooks", "/grants", "/discovery"]}
    />
  );
}
