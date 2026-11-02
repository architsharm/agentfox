import Link from "next/link";

import { COPY } from "@/lib/lp/copy";
import type { Variant } from "@/lib/lp/variants";

import { Reveal } from "./client";
import { FlowArt } from "./FlowArt";
import { ProductScene } from "./ProductScene";
import { Arrow, LpFooter, LpNav, SectionHead, WORKS_WITH } from "./parts";

/**
 * Page one of a variant. Every section has the same shape (label, heading, one
 * line, then a visual) and uses the same type scale (lp.css).
 */
export function Landing({ v }: { v: Variant }) {
  const c = COPY[v.slug];
  return (
    <div className="lp">
      <Reveal />
      <LpNav slug={v.slug} />
      <main>
        <section className="lp-hero">
          <FlowArt mode={v.slug} />
          <div className="lp-hero-copy">
            <span className="lp-pill">Open source · Self-hosted</span>
            <h1>
              {c.h1[0]}
              <br />
              <span className="lp-muted">{c.h1[1]}</span>
            </h1>
            <p className="lp-lead">{c.tagline}</p>
            <div className="lp-actions">
              <Link href="/docs/quickstart" className="lp-btn lp-btn-primary">
                Get started <Arrow />
              </Link>
              <Link href={`/lp/${v.slug}/benchmark`} className="lp-btn lp-btn-secondary">
                See the benchmark
              </Link>
            </div>
          </div>
          <div className="lp-logos">
            <span className="lp-logos-label">Works with</span>
            <div className="lp-logos-track">
              <div className="lp-logos-run">
                {WORKS_WITH.map((w) => (
                  <span key={w}>{w}</span>
                ))}
              </div>
              <div className="lp-logos-run" aria-hidden>
                {WORKS_WITH.map((w) => (
                  <span key={w}>{w}</span>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="lp-section">
          <div className="lp-wrap">
            <SectionHead eyebrow={c.scene.eyebrow} title={c.scene.title} sub={c.scene.sub} />
            <div className="lp-stage" data-reveal>
              <ProductScene mode={v.slug} />
            </div>
          </div>
        </section>

        <section className="lp-section lp-section-alt">
          <div className="lp-wrap">
            <SectionHead eyebrow="Benchmark" title="Measured against the tools you use today" />
            <div className="lp-stats" data-reveal>
              {c.stats.map((s) => (
                <div key={s.label} className="lp-stat">
                  <span className="lp-stat-n">{s.n}</span>
                  <span className="lp-stat-l">{s.label}</span>
                  <span className="lp-stat-vs">{s.vs}</span>
                </div>
              ))}
            </div>
            <p className="lp-center-link">
              <Link href={`/lp/${v.slug}/benchmark`}>
                Full results and rerun scripts <Arrow />
              </Link>
            </p>
          </div>
        </section>

        <section className="lp-section">
          <div className="lp-wrap">
            <SectionHead eyebrow="Use cases" title={c.uses.title} />
            <div className="lp-cards" data-reveal>
              {c.uses.items.map((u) => (
                <article key={u.title} className="lp-card">
                  <h3>{u.title}</h3>
                  <p>{u.line}</p>
                </article>
              ))}
            </div>
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
              <a href="https://github.com/architsharm/agentfox" className="lp-btn lp-btn-ghost" target="_blank" rel="noreferrer">
                View on GitHub
              </a>
            </div>
          </div>
        </section>
      </main>
      <LpFooter slug={v.slug} />
    </div>
  );
}
