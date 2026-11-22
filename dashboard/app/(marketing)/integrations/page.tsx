import type { Metadata } from "next";
import Link from "next/link";

import { DocSection, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { INTEGRATIONS, integrationPath } from "@/lib/marketing/integrations";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Guardrails for LangChain, LangGraph, CrewAI, the OpenAI Agents SDK, Claude Code and MCP",
  description:
    "What AgentFox checks for each agent framework and coding agent, and how: one line for Python frameworks, hooks for Claude Code and Codex, a scan and a governor for MCP.",
  path: "/integrations",
});

export default function IntegrationsPage() {
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <h1>
              Your framework
              <br />
              <span className="lp-muted">and what gets checked in it</span>
            </h1>
            <p className="lp-lead">
              One page per framework: the three lines to add, what each check reads, where it runs, and what it does not
              see. Nothing here claims more than the docs page it links to.
            </p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection id="frameworks" title="Pick yours">
            <Table
              head={["Framework", "What one page says"]}
              rows={INTEGRATIONS.map((i) => ({
                cells: [<Link key={i.slug} href={integrationPath(i.slug)}>{i.name}</Link>, i.description],
              }))}
            />
            <p className="lp-doc-more">
              <Link href="/docs/connect">
                Something else: LiteLLM, OpenClaw, voice platforms, TypeScript, any language over HTTP <Arrow />
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
