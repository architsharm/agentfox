import type { Metadata } from "next";
import Link from "next/link";

import { DocSection } from "@/components/lp/bench";
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
    "AgentFox benchmarks we rerun, and our papers on guardrails for AI agents accepted at workshops in December 2026: detection, latency and what a guardrail does when it fails.",
  path: "/research",
});

type Work = {
  /** What it was accepted as, and where and when it is presented. */
  accepted: string;
  venue: string;
  host: string;
  when: string;
  title: string;
  finding: React.ReactNode;
  limit: string;
  link?: { href: string; label: string };
};

const PAPERS: Work[] = [
  {
    accepted: "Accepted, to be presented at",
    venue: "WAITI 2026",
    host: "ACSAC 2026 workshops",
    when: "7 December 2026, Los Angeles",
    title:
      "No Tier Wins Everywhere: Benchmarking Rules, Classifiers, a Judgment Model and an LLM as Security Detectors for AI Agents",
    finding:
      "Five kinds of detector compared on the same rows across eight kinds of security decision: 21 labelled datasets, 175,816 labelled decisions. Code is exact on parsed structure, a local open-source classifier matches a hosted model on held-out prompt injection, and on injected agent actions only argument provenance contains every attack, at a large cost in benign tasks.",
    limit: "One LLM with one prompt; the hosted judgment model's version could not be pinned.",
    link: { href: "https://github.com/architsharm/waiti2026-artifact", label: "Per-row decisions and scripts" },
  },
  {
    accepted: "Accepted, to be presented at",
    venue: "IEEE BigData 2026",
    host: "Trustworthy AI Pipelines workshop",
    when: "December 2026, Phoenix",
    title: "What a Runtime Guardrail Costs an Agent Pipeline: A Latency Case Study on Open-Source Agent Repositories",
    finding:
      "The latency of AgentFox's own checks on sessions generated from agent repositories: deterministic checks cost 3.5 ms at the median, a prompt-injection classifier raised that to 47 ms, and an inline LLM judge cost about a second. Under load, checks that skipped the classifier to meet their deadline also lost its detection.",
    limit: "One gateway worker on SQLite; the production configuration was not tested.",
  },
  {
    accepted: "Accepted, to be presented at",
    venue: "IEEE BigData 2026",
    host: "Trustworthy and Aligned AI workshop",
    when: "December 2026, Phoenix",
    title:
      "When the Guardrail Breaks: Failure Semantics of Open-Source Guardrails for LLM Agents and What They Mean for Control",
    finding:
      "What 16 guardrail libraries, gateways, frameworks and agent hooks do when a detector errors or times out. On a detector error, 7 raise to the caller, 3 block, 5 let the call proceed and 1 mixes both. The study also found a fail-open bug in AgentFox, which is fixed.",
    limit: "All coding was done by LLM agents; 27 rows were confirmed by fault injection, and no person checked the rest.",
  },
];

const DEMOS: Work[] = [
  {
    accepted: "Demo accepted, to be shown at",
    venue: "Cross-AI Symposium 2026",
    host: "Self-Evolving AI Safety session",
    when: "14 to 16 December 2026, online",
    title: "Observe-First Runtime Guardrails and Provenance Holds for Tool-Using Agents",
    finding:
      "AgentFox on a local build: an over-limit payment blocked, a poisoned document stopped, an unregistered agent flagged, a call held for a person because an argument came from a tool result, and the audit chain verified.",
    limit: "The video replays fixed scenarios without a live LLM.",
    link: { href: "https://youtu.be/_ofXWW5uK38", label: "Watch the demo" },
  },
];

/** One row of the ruled list: where it is presented on the left, the work on the right. */
function WorkRow({ work }: { work: Work }) {
  return (
    <article className="lp-work">
      <div className="lp-work-meta">
        <span>{work.accepted}</span>
        <b>{work.venue}</b>
        <span>{work.host}</span>
        <span>{work.when}</span>
      </div>
      <div className="lp-work-body">
        <h3>{work.title}</h3>
        <p>{work.finding}</p>
        <p className="lp-work-limit">
          <strong>Limit:</strong> {work.limit}
        </p>
        {work.link && (
          <a className="lp-paper-link" href={work.link.href} target="_blank" rel="noreferrer">
            {work.link.label} <Arrow />
          </a>
        )}
      </div>
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
            <h1>
              What we measure,
              <br />
              <span className="lp-muted">and what it doesn&apos;t show</span>
            </h1>
            <p className="lp-lead">
              The benchmarks behind AgentFox, rerun when the product changes, and the papers we present at
              workshops in December. Every result states its limits.
            </p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection
            id="benchmarks"
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
            title="Accepted papers"
            lead="Each is accepted and will be presented in December 2026. Where a paper measures “the authors’ guardrail”, that guardrail is AgentFox."
          >
            <div className="lp-works" data-reveal>
              {PAPERS.map((w) => (
                <WorkRow key={w.title} work={w} />
              ))}
            </div>
          </DocSection>

          <DocSection id="demos" title="Demos">
            <div className="lp-works" data-reveal>
              {DEMOS.map((w) => (
                <WorkRow key={w.title} work={w} />
              ))}
            </div>
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
