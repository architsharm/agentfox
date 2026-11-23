import type { Metadata } from "next";
import Link from "next/link";

import { DocSection, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { TEMPLATES, templatePath } from "@/lib/marketing/templates";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Agent templates: example agents with their AgentFox policy",
  description:
    "Example agents (coding, support, browser, SQL, MCP) with their tools, the AgentFox policy that governs them, and an attack each one stops, every verdict checked by running the policy.",
  path: "/templates",
});

export default function TemplatesPage() {
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <h1>
              Agent templates
              <br />
              <span className="lp-muted">a policy to start from, for the agent you are building</span>
            </h1>
            <p className="lp-lead">
              Each template is an example agent: its tools, the lines that grant them, and an attack the policy stops.
              Every verdict on these pages is what AgentFox returned when the policy was run.
            </p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection id="templates" title="Pick the closest one">
            <Table
              head={["Agent", "What its page shows"]}
              rows={[
                ...TEMPLATES.map((t) => ({
                  cells: [<Link key={t.slug} href={templatePath(t.slug)}>{t.name}</Link>, t.description],
                })),
                {
                  cells: [
                    <Link key="openclaw" href="/openclaw">OpenClaw</Link>,
                    "A whole open-source agent, run for a team with every shell command, browser step and message checked first. One command to start.",
                  ],
                },
              ]}
            />
            <p className="lp-doc-more">
              <Link href="/integrations">
                Connect your framework: LangChain, LangGraph, CrewAI, the OpenAI Agents SDK and more <Arrow />
              </Link>
            </p>
          </DocSection>
        </div>

        <LpCta />
      </main>
      <LpFooter />
    </div>
  );
}
