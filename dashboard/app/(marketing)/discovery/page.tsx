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
    why: "Model clients and frameworks, with the file and line.",
  },
  {
    what: "Shadow agents",
    how: "A laptop session",
    why: "A coding session that was never committed.",
  },
  {
    what: "MCP servers and tools",
    how: "A fingerprint of the tools",
    why: "Recorded with a digest, so a later change shows up.",
  },
  {
    what: "Skills",
    how: "included in the repo scan",
    why: "Instructions the model will follow, including the parts nobody proofreads.",
  },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="AI-SPM"
      title={["Agents, tools and", "MCP servers you run"]}
      lede="In your repositories, your configs, and sessions on this machine. Cloud accounts are not scanned yet. If nobody owns one, it is listed."
      docs="/docs/guides/scan-a-repo"
      challenge={
        <p>Most of them were never written down.</p>
      }
      feature={{
        title: "Four kinds of thing",
        lede: "Each one is found a different way.",
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
          body: <p>It reports what it finds. It does not import the project, or send it anywhere.</p>,
        },
        {
          title: "Then look at what is actually running",
          body: <p>Session state on the machine catches the agent that never landed in git.</p>,
        },
        {
          title: "An agent with no owner is a finding",
          body: <p>After an incident, the first question is who operates it.</p>,
        },
      ]}
      gaps={{
        title: "What discovery does not do",
        body: (
          <p>
            It only sees the repositories and machines you point it at. An agent built
            at runtime from configuration it has never been shown stays invisible.
          </p>
        ) }}
      related={["/grants", "/mcp", "/hooks"]}
    />
  );
}
