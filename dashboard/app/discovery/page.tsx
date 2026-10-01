import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "AI-SPM: agents, tools, MCP servers and skills",
  description:
    "Agents, tools, MCP servers and skills in your repositories, and on laptops where they were never committed.",
  path: "/discovery",
});

const FINDS = [
  {
    what: "Agents",
    how: "Committed code",
    why: "Model clients and agent frameworks in committed code, with the file and line.",
  },
  {
    what: "Shadow agents",
    how: "A laptop session",
    why: "Local coding-assistant session state — the agent someone is using today that was never committed.",
  },
  {
    what: "MCP servers and tools",
    how: "A fingerprint of the tools",
    why: "Recorded with a digest, which is the only thing that makes a later change detectable.",
  },
  {
    what: "Skills",
    how: "included in the repo scan",
    why: "Instructions the model will follow, read for planted directives and shell fences.",
  },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="AI-SPM"
      title={["Every agent, tool,", "and MCP server"]}
      lede="In your repositories, and on laptops where they were never committed. If nobody owns one, it is listed."
      docs="/docs/discovery"
      challenge={
        <p>
          Agents get built quickly and rarely get written down. By the time someone
          asks what is running, the answer is spread across a few repos and
          somebody&rsquo;s laptop.
        </p>
      }
      feature={{
        title: "Four kinds of thing, four ways of finding them",
        lede: "Each is found a different way.",
        body: (
          <div className="find-grid mk-stagger">
            {FINDS.map((f) => (
              <div key={f.what} className="find">
                <b>{f.what}</b>
                <span>{f.how}</span>
                <p>{f.why}</p>
              </div>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "Read the code without running it",
          body: (
            <p>
              Point it at a repository and it reports every model client, tool call and
              agent framework it can find, with the file and line. Static analysis, so a
              scan costs nothing and cannot have side effects.
            </p>
          ),
        },
        {
          title: "Find what is actually running",
          body: (
            <p>
              Committed code is a poor proxy for live behaviour. Local coding-assistant
              session state is a second signal, and it catches the agent somebody is
              using today that was never committed anywhere.
            </p>
          ),
        },
        {
          title: "Snapshot the tool servers",
          body: (
            <p>
              Every MCP server&rsquo;s tools are recorded with a digest, which is what
              makes a later change detectable. Hygiene problems in the descriptions are
              raised at the same time.
            </p>
          ),
        },
        {
          title: "Read the skills, including the parts nobody proofreads",
          body: (
            <p>
              A skill file is instructions the model will follow. They are parsed for
              planted directives and shell fences — and frontmatter that will not parse
              is reported and kept, not silently discarded, because discarding it is how
              a poisoned skill scans clean.
            </p>
          ),
        },
        {
          title: "Attach an owner, or raise a finding",
          body: (
            <p>
              Every agent in the registry has a state — active, quarantined or killed —
              and an owner. An agent with no owner is a reportable finding rather than a
              row in a table, because the first question after an incident is who
              operates this.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "What discovery does not do",
        body: (
          <p>
            It reads repositories and local session state. It does not sweep employee
            laptops through an EDR or MDM, so an agent on a machine nobody points it at
            stays invisible — that is a distribution gap, not a detection one. Static
            analysis also cannot see an agent assembled at runtime from configuration it
            has never been shown.
          </p>
        ) }}
      related={["/grants", "/mcp", "/hooks"]}
    />
  );
}
