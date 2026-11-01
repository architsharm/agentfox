import Link from "next/link";

import { AGENTDOJO, AGENT_TIERS, FALSE_FLAGS, LATENCY_H2H, METHOD_NOTE, RERUN, SOURCES } from "@/lib/lp/proof";
import type { Variant } from "@/lib/lp/variants";

import { CopyChip, Reveal } from "./client";
import { FlowArt } from "./FlowArt";
import { Arrow, LpFooter, LpNav, SectionHead } from "./parts";

/** Page two: each comparison as one card, on the same type scale as page one. */
export function Benchmark({ v }: { v: Variant }) {
  const tests = v.benchmarkOrder.map((k) => TESTS[k]);
  return (
    <div className="lp">
      <Reveal />
      <LpNav slug={v.slug} />
      <main>
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <span className="lp-pill">Benchmark · October 2026</span>
            <h1>
              Measured against
              <br />
              <span className="lp-muted">the guardrails you use today</span>
            </h1>
            <p className="lp-lead">Public datasets, one machine, each tool at its default. Including where we lose.</p>
          </div>
        </section>

        <section className="lp-section">
          <div className="lp-wrap lp-tests">
            {tests.map((t, i) => (
              <article key={t.q} className="lp-test" data-reveal>
                <div className="lp-test-side">
                  <span className="lp-pill">Test {i + 1}</span>
                  <h3>{t.q}</h3>
                  <span className="lp-stat-n">{t.n}</span>
                  <p>{t.cap}</p>
                </div>
                <div className="lp-test-main">
                  <table className="lp-table">
                    <thead>
                      <tr>
                        {t.head.map((h, j) => (
                          <th key={j}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {t.rows.map((r, j) => (
                        <tr key={j} className={r.ours ? "is-ours" : undefined}>
                          {r.cells.map((c, k) => (
                            <td key={k}>{c}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="lp-test-foot">
                    <CopyChip text={t.rerun} />
                    <a href={t.source} target="_blank" rel="noreferrer">
                      Method <Arrow />
                    </a>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="lp-section lp-section-alt">
          <div className="lp-wrap">
            <SectionHead eyebrow="Honest results" title="Where we lose" />
            <div className="lp-cards" data-reveal>
              <article className="lp-card">
                <span className="lp-stat-n">
                  {AGENTDOJO.benignCompleted.agentfox}/{AGENTDOJO.benignTasks}
                </span>
                <p>Normal AgentDojo tasks that run without review. LLM Guard: {AGENTDOJO.benignCompleted.llmGuard}.</p>
              </article>
              <article className="lp-card">
                <span className="lp-stat-n">66.7%</span>
                <p>Precision on attacks hidden in tool output. LLM Guard: 81.8%.</p>
              </article>
              <article className="lp-card">
                <span className="lp-stat-n">25 ms</span>
                <p>Prompt Guard 2 (22M) is faster, and checks injection only.</p>
              </article>
            </div>
            <p className="lp-note">{METHOD_NOTE}</p>
          </div>
        </section>

        <section className="lp-cta">
          <div className="lp-wrap lp-cta-in">
            <h2>Try AgentFox on your own agent</h2>
            <p className="lp-lead">Starts in watch mode. Nothing is blocked until you say so.</p>
            <div className="lp-actions">
              <Link href="/docs/quickstart" className="lp-btn lp-btn-primary">
                Get started <Arrow />
              </Link>
              <Link href={`/lp/${v.slug}`} className="lp-btn lp-btn-ghost">
                Back to overview
              </Link>
            </div>
          </div>
        </section>
      </main>
      <LpFooter slug={v.slug} />
    </div>
  );
}

type Test = {
  q: string;
  n: string;
  cap: string;
  head: string[];
  rows: { cells: string[]; ours?: boolean }[];
  rerun: string;
  source: string;
};

const TESTS: Record<Variant["benchmarkOrder"][number], Test> = {
  runtime: {
    q: "Does the attack still run?",
    n: "0 / 588",
    cap: "AgentDojo attacks that ran. Still 0 with every detector off.",
    head: ["", "Attacks ran", "Tasks without review", "Per tool call"],
    rows: [
      { cells: ["No guardrail", "588", "97", "–"] },
      { cells: ["LLM Guard", "86", String(AGENTDOJO.benignCompleted.llmGuard), `${AGENTDOJO.perToolCallMs.llmGuard} ms`] },
      { cells: ["AgentFox", "0", String(AGENTDOJO.benignCompleted.agentfox), `${AGENTDOJO.perToolCallMs.agentfox} ms`], ours: true },
      { cells: ["AgentFox, detectors off", "0", String(AGENTDOJO.benignCompleted.agentfox), `${AGENTDOJO.perToolCallMs.containmentOnly} ms`], ours: true },
    ],
    rerun: RERUN.agentdojo,
    source: SOURCES.agentdojoH2H,
  },
  latency: {
    q: "How long does a check take?",
    n: "63 ms",
    cap: "Median for five checks, on 880 messages.",
    head: ["", "Checks for", "Median", "p95"],
    rows: LATENCY_H2H.map((r) => ({ cells: [r.name, r.checks, `${r.value} ms`, `${r.p95} ms`], ours: r.ours })),
    rerun: RERUN.latency,
    source: SOURCES.latencyH2H,
  },
  falseflags: {
    q: "How often is a harmless message blocked?",
    n: "11.5%",
    cap: "Of 339 harmless look-alike prompts. LLM Guard's model: 42.2%.",
    head: ["", "Harmless flagged", "Attacks caught"],
    rows: FALSE_FLAGS.rows.map((r) => ({ cells: [r.name, r.flagged, r.caught], ours: "ours" in r && r.ours })),
    rerun: RERUN.falseflags,
    source: SOURCES.injection,
  },
  agents: {
    q: "What does a one-message scanner miss?",
    n: "3 of 4",
    cap: "Agent attack types LLM Guard can't check or misreads.",
    head: ["", "LLM Guard", "AgentFox"],
    rows: AGENT_TIERS.map((t) => ({ cells: [t.test, t.llmGuard, t.agentfox] })),
    rerun: RERUN.agents,
    source: SOURCES.agentSecurity,
  },
};
