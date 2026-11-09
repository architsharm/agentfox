import type { Metadata } from "next";
import { publicPageMetadata } from "@/lib/site";
import Link from "next/link";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/lib/product/api";
import { Logo } from "@/components/product/Logo";
import { configuredSignIns } from "@/lib/product/oauth";
import { ThemeButton } from "@/components/lp/client";

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
    "Sign in to AgentFox with Google, GitHub or Microsoft. A new sign-in creates your workspace.",
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

function GoogleMark() {
  return (
    <svg width="17" height="17" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

function MicrosoftMark() {
  return (
    <svg width="15" height="15" viewBox="0 0 21 21" aria-hidden="true">
      <path fill="#f25022" d="M1 1h9v9H1z" />
      <path fill="#7fba00" d="M11 1h9v9h-9z" />
      <path fill="#00a4ef" d="M1 11h9v9H1z" />
      <path fill="#ffb900" d="M11 11h9v9h-9z" />
    </svg>
  );
}

/**
 * The measurement on the brand wall.
 *
 * It is the same experiment the home page leads its proof section with, and the
 * same figures, because a visitor who followed a link from there and is now
 * deciding whether to hand over a GitHub identity should meet the claim they
 * already read rather than a second, different one. The benign-task cost of that
 * containment (24 of 97 ran without a person) is stated on the benchmark page, where
 * it has its context; on a sign-in card it read as the product failing. The source is
 * benchmarks/agentdojo/results/inferred_provenance_summary.json and
 * benchmarks/adaptive/results/adaptive_summary.json; both ratios are bound in
 * benchmarks/claims.yaml and checked by scripts/check/claims.py, which also fails if a retired AgentDojo figure reappears.
 */
const PROOF: [string, string][] = [
  ["588 of 588", "attack pairs contained"],
  ["37 of 37", "attacks that got past the detector, still stopped before they acted"],
];

/**
 * Sign-in and sign-up are the same step: a new identity creates a workspace. The page
 * says that once and otherwise gets out of the way. Each provider's button shows only
 * when this deployment is set up to finish it (lib/product/oauth.ts).
 */
export default async function Login({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; expired?: string; deleted?: string }>;
}) {
  const { error, expired, deleted } = await searchParams;
  // Middleware clears the stale cookie on its way here (see middleware.ts), so
  // by this point an expired session has no cookie left to redirect on.
  if (!expired && (await cookies()).get(SESSION_COOKIE)?.value) {
    redirect("/app/welcome");
  }
  const can = configuredSignIns();
  const none = !can.github && !can.google && !can.microsoft;

  return (
    <main className="auth">
      <div className="auth-form">
        <div className="auth-theme lp-x">
          <ThemeButton />
        </div>
        <div className="auth-inner">
          <Link href="/" className="auth-brand">
            <Logo size={26} />
            <span>
              <b>AgentFox</b>
            </span>
          </Link>

          <h1>Sign in to AgentFox</h1>
          <p className="sub">New here? Signing in creates your workspace.</p>

          {deleted && (
            <p className="small muted" role="status" style={{ margin: "18px 0 0" }}>
              Your account and its workspace were deleted.
            </p>
          )}
          {expired && (
            <div className="error small" style={{ margin: "18px 0 0" }}>
              Your session expired. Sign in again to pick up where you left off.
            </div>
          )}
          {error && (
            <div className="error small" style={{ margin: "18px 0 0" }}>
              {error}
            </div>
          )}

          <div className="auth-buttons">
            {can.google && (
              <a className="btn-oauth" href="/api/auth/google/login">
                <GoogleMark />
                Continue with Google
              </a>
            )}
            {can.github && (
              <a className="btn-oauth" href="/api/auth/github/login">
                <GitHubMark />
                Continue with GitHub
              </a>
            )}
            {can.microsoft && (
              <a className="btn-oauth" href="/api/auth/microsoft/login">
                <MicrosoftMark />
                Continue with Microsoft
              </a>
            )}
            {none && (
              <p className="small muted">
                No sign-in provider is set up on this deployment. Use an API token below.
              </p>
            )}
          </div>

          {/* Self-hosted installs often have no OAuth app. The operator mints a token on
              the gateway host and signs in with it (api/auth/token/route.ts). */}
          <details className="auth-token" open={none}>
            <summary className="small muted">Sign in with an API token</summary>
            <form action="/api/auth/token" method="POST">
              <input
                id="token"
                name="token"
                type="password"
                autoComplete="off"
                placeholder="nom_api_…"
                aria-label="API token"
                required
              />
              <button type="submit" className="btn-primary auth-submit">
                Sign in
              </button>
              <p className="small muted">Self-hosted? Create one on the gateway host with</p>
              <pre className="auth-cmd">
                <code>agentfox admin users create you@example.com --role owner --token</code>
              </pre>
            </form>
          </details>

          <p className="auth-foot small muted">
            Just looking? <Link href="/playground">Try the playground</Link>, no account needed.
            <br />
            By continuing you confirm you are 18 or older and agree to the{" "}
            <Link href="/terms">Terms</Link> and <Link href="/privacy">Privacy Policy</Link>.
          </p>
        </div>
      </div>

      <aside className="auth-wall" aria-label="What AgentFox does">
        <div className="auth-wall-inner">
          <h2>Guardrails that don&apos;t block your real customers</h2>
          <p>
            The headline results from our <Link href="/benchmark">security benchmarks</Link>: AgentDojo&apos;s attack pairs,
            and an attacker who rewrites each attack after seeing our verdict.
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
