/**
 * Building blocks for the landing-page variants (app/(lp)), in the product's own
 * visual language: af-theme.css tokens, `//` mono comments, verdict pills,
 * hairline cards, rose for the one primary action.
 */

import Link from "next/link";
import { cookies } from "next/headers";

import { FOOTER, HEADER, HEADER_CTA } from "@/lib/marketing/nav";
import { SESSION_COOKIE } from "@/lib/product/api";

import { Logo } from "@/components/product/Logo";
import { CopyChip, ThemeButton } from "./client";
import { REPO_URL, SUPPORT_EMAIL } from "@/lib/site";


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

/** The header on every public page: the home page, the marketing pages, the docs and the blog. */
export async function LpNav() {
  const signedIn = Boolean((await cookies()).get(SESSION_COOKIE)?.value);
  return (
    <header className="lp-nav lp-x">
      <div className="lp-nav-in">
        <Link href="/" className="lp-brand" aria-label="AgentFox home">
          <Logo size={22} />
          <span>AgentFox</span>
        </Link>
        <nav className="lp-nav-links" aria-label="Main">
          {HEADER.map((it) => (
            <Link key={it.href} href={it.href}>
              {it.label}
            </Link>
          ))}
        </nav>
        <div className="lp-nav-cta">
          <a href={REPO_URL} target="_blank" rel="noreferrer" aria-label="Source on GitHub" className="lp-iconbtn">
            <GitHubIcon />
          </a>
          <ThemeButton />
          <Link href={signedIn ? "/app" : "/login"} className="lp-nav-text">
            {signedIn ? "Dashboard" : "Sign in"}
          </Link>
          <Link href={HEADER_CTA.href} className="lp-btn lp-btn-primary lp-btn-sm">
            {HEADER_CTA.label}
          </Link>
          <details className="lp-menu">
            <summary aria-label="Menu">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
                <path d="M4 7h16M4 12h16M4 17h16" />
              </svg>
            </summary>
            <div className="lp-menu-panel">
              {HEADER.map((it) => (
                <Link key={it.href} href={it.href}>
                  {it.label}
                </Link>
              ))}
              <Link href={signedIn ? "/app" : "/login"}>{signedIn ? "Dashboard" : "Sign in"}</Link>
            </div>
          </details>
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

/** The footer on every public page. */
export function LpFooter() {
  return (
    <footer className="lp-foot lp-x">
      <div className="lp-wrap lp-foot-in">
        <div className="lp-foot-brand">
          <span className="lp-brand">
            <Logo size={22} />
            <span>AgentFox</span>
          </span>
          <p>Runtime guardrails for AI agents. Open source under Apache-2.0.</p>
          <a href={`mailto:${SUPPORT_EMAIL}`} className="lp-foot-mail">
            {SUPPORT_EMAIL}
          </a>
        </div>
        <div className="lp-foot-cols">
          {FOOTER.map((c) => (
            <div key={c.heading} className="lp-foot-col">
              <span>{c.heading}</span>
              {c.items.map((it) => (
                <Link key={it.href} href={it.href}>
                  {it.label}
                </Link>
              ))}
              {c.heading === "Resources" && (
                <a href={REPO_URL} target="_blank" rel="noreferrer">
                  GitHub
                </a>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="lp-wrap lp-foot-legal">
        <span>© 2026 Nometria, Inc.</span>
      </div>
    </footer>
  );
}

/** The closing block on the home page, the benchmark and the blog. */
export function LpCta() {
  return (
    <section className="lp-cta lp-x">
      <div className="lp-wrap lp-cta-in">
        <h2>Try AgentFox on your own agent</h2>
        <p className="lp-lead">One command finds your agents. It starts in watch mode, so nothing is blocked until you say so.</p>
        <div className="lp-start">
          <CopyChip text="uvx agentfox scan" />
        </div>
        <div className="lp-actions">
          <Link href="/docs/quickstart" className="lp-btn lp-btn-primary">
            Read the quickstart <Arrow />
          </Link>
          <a href={REPO_URL} className="lp-btn lp-btn-ghost" target="_blank" rel="noreferrer">
            View on GitHub
          </a>
        </div>
      </div>
    </section>
  );
}
