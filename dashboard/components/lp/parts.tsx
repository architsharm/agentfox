/**
 * Building blocks for the landing-page variants (app/(lp)), in the product's own
 * visual language: af-theme.css tokens, `//` mono comments, verdict pills,
 * hairline cards, rose for the one primary action.
 */

import Link from "next/link";
import { cookies } from "next/headers";

import { FLAT, GROUPS, SECONDARY } from "@/lib/marketing/nav";
import { SESSION_COOKIE } from "@/lib/product/api";

import { Logo } from "@/components/product/Logo";
import { REPO_URL, SUPPORT_EMAIL } from "@/lib/site";
import type { VariantSlug } from "@/lib/lp/variants";


const GITHUB_PATH =
  "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z";

export function GitHubIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d={GITHUB_PATH} />
    </svg>
  );
}

export function Arrow() {
  return (
    <svg className="lp-arrow" viewBox="0 0 12 12" aria-hidden>
      <path d="M3 9 9 3M4 3h5v5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export async function LpNav({ slug, home }: { slug: VariantSlug; home?: string }) {
  const signedIn = Boolean((await cookies()).get(SESSION_COOKIE)?.value);
  return (
    <header className="lp-nav">
      <div className="lp-nav-in">
        <Link href={home ?? `/lp/${slug}`} className="lp-brand" aria-label="AgentFox home">
          <Logo size={22} />
          <span>AgentFox</span>
        </Link>
        <div className="lp-nav-cta">
          <a href={REPO_URL} target="_blank" rel="noreferrer" aria-label="Source on GitHub" className="lp-iconbtn">
            <GitHubIcon />
          </a>
          <Link href={signedIn ? "/app" : "/login"} className="lp-nav-text">
            {signedIn ? "Dashboard" : "Sign in"}
          </Link>
          <Link href="/docs/quickstart" className="lp-btn lp-btn-primary lp-btn-sm">
            Get started <Arrow />
          </Link>
        </div>
      </div>
    </header>
  );
}

/** A section label in the product's comment voice. */
export function Comment({ children }: { children: React.ReactNode }) {
  return <p className="lp-comment">{children}</p>;
}

export function SectionHead({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: string }) {
  return (
    <div className="lp-head">
      <span className="lp-pill">{eyebrow}</span>
      <h2>{title}</h2>
      {sub && <p className="lp-lead">{sub}</p>}
    </div>
  );
}

export const WORKS_WITH = [
  "LangGraph",
  "LangChain",
  "OpenAI Agents SDK",
  "CrewAI",
  "AutoGen",
  "Google ADK",
  "MCP",
  "LiteLLM",
];

/**
 * The footer carries the whole site map (lib/marketing/nav.ts, the same source as
 * the sitemap and llms.txt), quietly, so the top of the page can stay minimal.
 */
export function LpFooter({ slug: _slug }: { slug: VariantSlug }) {
  const columns = GROUPS.flatMap((g) =>
    g.sections.map((sec) => ({ heading: sec.heading || g.label, items: sec.items })),
  );
  return (
    <footer className="lp-foot">
      <div className="lp-wrap lp-foot-in">
        <div className="lp-foot-brand">
          <span className="lp-brand">
            <Logo size={22} />
            <span>AgentFox</span>
          </span>
          <p>Runtime guardrails for AI agents. Open source under Apache-2.0, by Nometria.</p>
          <a href={`mailto:${SUPPORT_EMAIL}`} className="lp-foot-mail">
            {SUPPORT_EMAIL}
          </a>
        </div>
        <div className="lp-foot-cols">
          {columns.map((c) => (
            <div key={c.heading} className="lp-foot-col">
              <span>{c.heading}</span>
              {c.items.map((it) => (
                <Link key={it.href} href={it.href}>
                  {it.label}
                </Link>
              ))}
            </div>
          ))}
          <div className="lp-foot-col">
            <span>Try it</span>
            {FLAT.map((it) => (
              <Link key={it.href} href={it.href}>
                {it.label}
              </Link>
            ))}
            <a href={REPO_URL} target="_blank" rel="noreferrer">
              GitHub
            </a>
          </div>
        </div>
      </div>
      <div className="lp-wrap lp-foot-legal">
        <span>© 2026 Nometria, Inc.</span>
        <span className="lp-foot-legal-links">
          {SECONDARY.map((it) => (
            <Link key={it.href} href={it.href}>
              {it.label}
            </Link>
          ))}
        </span>
      </div>
    </footer>
  );
}
