import type { Metadata } from "next";
import Link from "next/link";

import { Contents, DocSection } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { publicPageMetadata } from "@/lib/site";

export const dynamic = "force-dynamic";

/*
 * The index of everything we measure and publish. The benchmarks keep their own pages
 * (and their numbers stay bound in benchmarks/claims.yaml there); this page only links
 * them. Paper figures are quoted from each paper's accepted abstract, which is fixed
 * once accepted, so they are not bound to a results file.
 *
 * Only accepted work goes here. A paper under review is left off: several venues are
 * double-blind, and a page tying a submission to AgentFox would break that.
 */

export const metadata: Metadata = publicPageMetadata({
  title: "Research",
  description:
    "AgentFox benchmarks we rerun, and our peer-reviewed papers on guardrails for AI agents: detection, latency and what a guardrail does when it fails.",
  path: "/research",
});

type Work = {
  venue: string;
  title: string;
  finding: React.ReactNode;
  limit: string;
  link?: { href: string; label: string };
};

const PAPERS: Work[] = [
  {
    venue: "Peer reviewed · WAITI 2026, ACSAC workshops",
    title:
      "No Tier Wins Everywhere: Benchmarking Rules, Classifiers, a Judgment Model and an LLM as Security Detectors for AI Agents",
    finding:
      "Five kinds of detector compared on the same rows across eight kinds of security decision: 21 labelled datasets, 175,816 labelled decisions. Code is exact on parsed structure, a local open-source classifier matches a hosted model on held-out prompt injection, and on injected agent actions only argument provenance contains every attack, at a large cost in benign tasks.",
    limit: "One LLM with one prompt; the hosted judgment model's version could not be pinned.",
    link: { href: "https://github.com/architsharm/waiti2026-artifact", label: "Per-row decisions and scripts" },
  },
  {
    venue: "Peer reviewed · IEEE BigData 2026, Trustworthy AI Pipelines workshop",
    title: "What a Runtime Guardrail Costs an Agent Pipeline: A Latency Case Study on Open-Source Agent Repositories",
    finding:
      "The latency of AgentFox's own checks on sessions generated from agent repositories: deterministic checks cost 3.5 ms at the median, a prompt-injection classifier raised that to 47 ms, and an inline LLM judge cost about a second. Under load, checks that skipped the classifier to meet their deadline also lost its detection.",
    limit: "One gateway worker on SQLite; the production configuration was not tested.",
  },
  {
    venue: "Peer reviewed · IEEE BigData 2026, Trustworthy and Aligned AI workshop",
    title:
      "When the Guardrail Breaks: Failure Semantics of Open-Source Guardrails for LLM Agents and What They Mean for Control",
    finding:
      "What 16 guardrail libraries, gateways, frameworks and agent hooks do when a detector errors or times out. On a detector error, 7 raise to the caller, 3 block, 5 let the call proceed and 1 mixes both. The study also found a fail-open bug in AgentFox, which is fixed.",
    limit: "All coding was done by LLM agents; 27 rows were confirmed by fault injection, and no person checked the rest.",
  },
];

const DEMOS: Work[] = [
  {
    venue: "Demo · Cross-AI Symposium 2026, Self-Evolving AI Safety session",
    title: "Observe-First Runtime Guardrails and Provenance Holds for Tool-Using Agents",
    finding:
      "AgentFox on a local build: an over-limit payment blocked, a poisoned document stopped, an unregistered agent flagged, a call held for a person because an argument came from a tool result, and the audit chain verified.",
    limit: "The video replays fixed scenarios without a live LLM.",
    link: { href: "https://youtu.be/_ofXWW5uK38", label: "Watch the demo" },
  },
];

const SECTIONS = [
  { id: "benchmarks", label: "Benchmarks we rerun" },
  { id: "papers", label: "Peer-reviewed papers" },
  { id: "demos", label: "Demos" },
];

function WorkCard({ work }: { work: Work }) {
  return (
    <article className="lp-paper" data-reveal>
      <span className="lp-pill">{work.venue}</span>
      <h3>{work.title}</h3>
      <p>{work.finding}</p>
      <p>
        <strong>Limit:</strong> {work.limit}
      </p>
      {work.link && (
        <a className="lp-paper-link" href={work.link.href} target="_blank" rel="noreferrer">
          {work.link.label} <Arrow />
        </a>
      )}
    </article>
  );
}

export default function ResearchPage() {
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <span className="lp-pill">Research</span>
            <h1>
              What we measure,
              <br />
              <span className="lp-muted">and what it doesn&apos;t show</span>
            </h1>
            <p className="lp-lead">
              The benchmarks behind AgentFox, rerun when the product changes, and the peer-reviewed papers they came from.
              Every result states its limits.
            </p>
          </div>
        </section>

        <section className="lp-section lp-section-tight">
          <div className="lp-wrap">
            <Contents items={SECTIONS} />
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection
            id="benchmarks"
            n={1}
            title="Benchmarks we rerun"
            lead="Each one has its own page with the method, the limits and the commands to rerun it."
          >
            <div className="lp-cards lp-cards-2" data-reveal>
              <Link href="/benchmark" className="lp-card">
                <h3>Security benchmark</h3>
                <p>
                  Containment with every detector off, an AgentDojo replay with its cost in benign tasks, detection against
                  other guards, and an adaptive attack.
                </p>
                <span className="lp-paper-link">
                  Read it <Arrow />
                </span>
              </Link>
              <Link href="/benchmark/latency" className="lp-card">
                <h3>Latency benchmark</h3>
                <p>What a guard check adds to an agent, on traffic from 109 real agent repositories, and against other guards on the same machine.</p>
                <span className="lp-paper-link">
                  Read it <Arrow />
                </span>
              </Link>
            </div>
          </DocSection>

          <DocSection
            id="papers"
            n={2}
            title="Peer-reviewed papers"
            lead="Accepted papers only. Where a paper measures “the authors’ guardrail”, that guardrail is AgentFox."
          >
            {PAPERS.map((w) => (
              <WorkCard key={w.title} work={w} />
            ))}
          </DocSection>

          <DocSection id="demos" n={3} title="Demos">
            {DEMOS.map((w) => (
              <WorkCard key={w.title} work={w} />
            ))}
            <p className="lp-doc-more">
              <Link href="/live">
                Our own agent, attacked every hour <Arrow />
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
