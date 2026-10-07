import type { Metadata } from "next";
import { publicPageMetadata } from "@/lib/site";
import Link from "next/link";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/lib/product/api";
import { Logo } from "@/components/product/Logo";

export const dynamic = "force-dynamic";

/**
 * Crawlable but not indexable, which is the right pair rather than a contradiction.
 *
 * app/robots.ts allows /login, because a `Disallow` would stop a crawler fetching
 * the page and therefore stop it ever seeing the `noindex` below. The `noindex`
 * itself is because a sign-in form is not a useful search result for anybody: the
 * queries it would answer are answered better by "/" or /how-it-works, and this is
 * also where every authenticated route redirects, so it is the page most at risk of
 * being indexed many times over under other URLs.
 *
 * It still carries a title, description and canonical, because those are what get
 * shown when somebody pastes the sign-in link into Slack.
 */
export const metadata: Metadata = publicPageMetadata({
  title: "Sign in or create a workspace",
  description:
    "Sign in to AgentFox with GitHub, which creates the workspace if you do not have one. The playground and the published benchmarks need no account at all.",
  path: "/login",
  noIndex: true,
});

/** GitHub's mark, drawn at the size the button uses it. `currentColor` so it takes
 *  the button's label colour rather than needing a second value for dark. */
function GitHubMark() {
  return (
    <svg width="17" height="17" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.42 7.42 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}

/**
 * The measurement on the brand wall.
 *
 * It is the same experiment the home page leads its proof section with, and the
 * same figures, because a visitor who followed a link from there and is now
 * deciding whether to hand over a GitHub identity should meet the claim they
 * already read rather than a second, different one. The source is
 * benchmarks/agentdojo/results/inferred_provenance_summary.json; the two
 * ratios here are bound to it in benchmarks/claims.yaml and checked by
 * scripts/check/claims.py, which also fails if a retired AgentDojo figure reappears.
 */
const PROOF: [string, string][] = [
  ["588 of 588", "attack pairs contained"],
  ["24 of 97", "benign tasks ran without escalating to a human"],
  ["0", "detectors switched on"],
];

/**
 * This page is the sign-up path as much as the sign-in one — a GitHub identity
 * nobody has seen before creates a new org on the far side of it — so it can't
 * greet everyone with "Welcome back". It also has to answer "what is this" for
 * a reader who arrived from a link and has no idea, and offer the one thing
 * that needs no account at all: the playground.
 */
export default async function Login({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; expired?: string }>;
}) {
  const { error, expired } = await searchParams;
  // Middleware clears the stale cookie on its way here (see middleware.ts), so
  // by this point an expired session has no cookie left to redirect on.
  if (!expired && (await cookies()).get(SESSION_COOKIE)?.value) {
    redirect("/app/start");
  }

  return (
    <main className="auth">
      <div className="auth-form">
        <div className="auth-inner">
          <Link href="/" className="auth-brand">
            <Logo size={26} />
            <span>
              <b>AgentFox</b>
              <span style={{ display: "block" }}>by Nometria</span>
            </span>
          </Link>

          <h1>Sign in, or start a workspace</h1>
          <p className="sub">
            Your agents, the rules they have to follow, and a record of what they did.
            GitHub opens the workspace.
          </p>

          {expired && (
            <div className="error small" style={{ margin: "18px 0 0" }}>
              Your session expired, so you were signed out. Signing in again picks up
              where you left off.
            </div>
          )}
          {error && (
            <div className="error small" style={{ margin: "18px 0 0" }}>
              {error}
            </div>
          )}

          <div style={{ marginTop: 26 }}>
            <a className="btn-github" href="/api/auth/github/login">
              <GitHubMark />
              Continue with GitHub
            </a>
          </div>
          <p className="small muted" style={{ marginTop: 12 }}>
            GitHub is also what lets you connect a repository so we can scan it for
            agents that need governing. We read code structure to detect what you are
            using, and never execute it.
          </p>

          {/* Self-hosted installs often have no GitHub OAuth app. The operator mints a
              token on the gateway host and signs in with it (api/auth/token/route.ts). */}
          <details style={{ marginTop: 18 }}>
            <summary className="small muted" style={{ cursor: "pointer" }}>
              Self-hosted? Sign in with an API token
            </summary>
            <form action="/api/auth/token" method="POST" style={{ marginTop: 10 }}>
              <label className="small muted" htmlFor="token">
                Create one on the gateway host:{" "}
                <code>agentfox admin users create you@example.com --role owner --token</code>
              </label>
              <input
                id="token"
                name="token"
                type="password"
                autoComplete="off"
                placeholder="nom_api_…"
                required
                style={{ display: "block", width: "100%", marginTop: 8 }}
              />
              <button type="submit" className="btn" style={{ marginTop: 8 }}>
                Sign in with token
              </button>
            </form>
          </details>

          <div className="auth-or">
            <span>or</span>
          </div>

          <Link href="/playground" className="auth-alt">
            <b>Try the playground first &rarr;</b>
            <span>
              Send a prompt at a sample agent and watch what gets refused. No account,
              nothing to install.
            </span>
          </Link>
        </div>
      </div>

      <aside className="auth-wall" aria-label="What AgentFox does">
        <div className="auth-wall-inner">
          <span className="auth-wall-eyebrow">Measured, not asserted</span>
          <h2>We turned the detectors off and ran it anyway</h2>
          <p>
            AgentDojo&apos;s ground truth, replayed with every detector disabled and provenance
            inferred from the real tool outputs. What was left is the part that does not depend
            on catching the attack, and what it costs.
          </p>
          <div className="auth-stats">
            {PROOF.map(([n, label]) => (
              <div key={label} className="auth-stat">
                <b>{n}</b>
                <span>{label}</span>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </main>
  );
}
