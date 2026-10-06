import type { Metadata } from "next";
import Link from "next/link";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { publicPageMetadata, REPO_URL, SUPPORT_EMAIL } from "@/lib/site";

export const dynamic = "force-dynamic";

/**
 * Every sentence on this page is a statement about code in this repository, and the
 * code is named beside it wherever a reader might reasonably want to check. A privacy
 * policy for a security product that cannot be checked is worth nothing, and this one
 * is short enough to check in an afternoon.
 *
 * Deliberately absent: a retention period nobody implemented, a list of sub-processors
 * copied from a template, and the phrase "industry-standard encryption".
 */
export const metadata: Metadata = publicPageMetadata({
  title: "Privacy policy",
  description:
    "What the hosted playground and GitHub sign-in actually store, for how long, the three companies that touch it, and why a copy you run yourself sends us nothing.",
  path: "/privacy",
});

const SRC = `${REPO_URL}/blob/main`;

/**
 * A source citation under a claim.
 *
 * `overflowWrap: anywhere` is load-bearing, not decoration. A path like
 * `dashboard/app/api/auth/github/callback/route.ts:97-103` is a single unbroken token
 * wider than a 375px viewport&rsquo;s content column, so without it the narrowest
 * phone gets a horizontal scrollbar on a page about trustworthiness.
 */
function Ref({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="mk-mono"
      style={{ color: "var(--mk-muted)", margin: "10px 0 0", overflowWrap: "anywhere" }}
    >
      {children}
    </p>
  );
}

export default function Privacy() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <span className="mk-eyebrow">Privacy</span>
              <h1 className="mk-h1" style={{ margin: "18px 0 0" }}>
                Privacy policy</h1>
              <p className="mk-lede" style={{ marginTop: 20 }}>
                What this site stores if you use the playground or sign in. A copy you
                run yourself sends us nothing.
              </p>
              <p className="mk-fine" style={{ marginTop: 16 }}>
                Last updated 24 September 2026.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">The playground</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The playground needs no account. It asks for no email address, no name and
                no payment details, and it has nowhere to put them. When you open it, the
                server creates a sandbox and hands you its id: 128 bits from a
                cryptographic random source. That id is the sandbox&rsquo;s tenant key and
                it is the only credential in the playground. It identifies no person.
              </p>
              <Ref>src/agentfox/apps/gateway/playground_sessions.py:23-26, 84-89</Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                What goes into a sandbox
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                The messages you type and the &ldquo;retrieved document&rdquo; you are
                invited to edit are sent to the server and written into your sandbox,
                verbatim, as conversation turns alongside the traces, decisions and
                findings your attacks produce. If you paste something into the playground,
                it is stored. Paste accordingly.
              </p>
              <Ref>
                src/agentfox/apps/gateway/routes/playground.py:87-143; src/agentfox/capabilities/containment/escalation.py:204-247
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Every one of those rows is written under an{" "}
                <span className="mk-mono">org_id</span> that is your sandbox id, so the
                same session-level tenant filter that separates two paying customers is
                what separates your sandbox from everyone else&rsquo;s. There is no
                playground-specific filter that somebody has to remember.
              </p>
              <Ref>
                src/agentfox/apps/gateway/playground_sessions.py:8-13; src/agentfox/core/tenancy.py:15-24
              </Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                How long it lives
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Thirty minutes of idle time. The clock is extended on every action, so it
                is thirty minutes since your last request, not since you arrived. When it
                runs out, every row belonging to that sandbox is deleted from every table,
                audit entries included, which are append-only everywhere else in the
                product. A sandbox is also dropped early, oldest idle one first, if more
                than 200 are live across the whole deployment at once.
              </p>
              <Ref>
                src/agentfox/apps/gateway/playground_sessions.py:57-66, 137-166, 282-286, 322-327
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Two things follow from the id being the only credential. Anyone you send
                your sandbox link to can read that sandbox. And the id cannot be revoked
                before it expires.
              </p>
              <Ref>src/agentfox/apps/gateway/playground_sessions.py:23-26</Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                Your IP address
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Used once, as the key for the per-address limit on how many sandboxes can
                be created in an hour, and held in the process&rsquo;s memory for that
                purpose only. It is not written to the database. The request address
                appears exactly once in the whole server codebase, on that line.
              </p>
              <Ref>src/agentfox/apps/gateway/routes/playground.py:49-50, 62-67</Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                No model provider is called
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                The playground is pinned to the offline provider, which is deterministic,
                keyless and network-free. Your prompt is never forwarded to OpenAI,
                Anthropic or anyone else, because nothing in a sandbox reaches the outside
                at all: the seeded <span className="mk-mono">payments.transfer</span> and{" "}
                <span className="mk-mono">email.send</span> tools you are encouraged to
                attack have no backend behind them.
              </p>
              <Ref>
                src/agentfox/apps/gateway/routes/playground.py:5-8, 127; src/agentfox/platform/providers/echo.py:1-6
              </Ref>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Signing in with GitHub</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Signing in creates a real account and a real organisation. A GitHub
                identity that has not been seen before becomes a brand new organisation
                with you as its owner, because there is no invite flow yet, so a new
                person and a new tenant are the same event.
              </p>
              <Ref>src/agentfox/apps/gateway/routes/integrations.py:116-163</Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                The fields stored about you
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Four: your GitHub numeric user id, your GitHub login, your name as GitHub
                reports it, and an email address. If your GitHub email is private, the
                primary address from GitHub&rsquo;s email endpoint is used; if that is not
                available either, the account is created against your GitHub{" "}
                <span className="mk-mono">users.noreply.github.com</span> address instead.
                That is the whole user record. There is no profile, no phone number and no
                billing row.
              </p>
              <Ref>
                dashboard/app/api/auth/github/callback/route.ts:62-91; src/agentfox/core/models/:397-406
              </Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                The GitHub access token
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Sign-in doubles as the grant that lets AgentFox list and scan your
                repositories, so the GitHub access token itself is stored, encrypted with
                Fernet under a key held in the deployment&rsquo;s environment rather than
                in the database. If that key is not configured, the request fails with a
                503 rather than storing the token in the clear. The raw token never reaches
                your browser: only the org-scoped id of the connection record does.
              </p>
              <Ref>
                dashboard/app/api/auth/github/callback/route.ts:97-103;
                src/agentfox/apps/gateway/routes/integrations.py:69-82, 181-214;
                src/agentfox/core/models/:421-434
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                A repository scan is static. Nothing in the scanner imports or executes the
                code it reads.
              </p>
              <Ref>src/agentfox/apps/gateway/routes/integrations.py:1-9</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Cookies</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Two, both strictly functional, both set by this site and nobody else.
              </p>
              <div className="mk-grid mk-grid-2" style={{ marginTop: 18 }}>
                <div className="mk-card">
                  <p className="mk-label">nometria_session</p>
                  <p className="mk-body" style={{ margin: "10px 0 0", fontSize: "var(--t-body)" }}>
                    The API token minted for you at sign-in, which is what the control
                    plane checks on every request. <span className="mk-mono">httpOnly</span>
                    , <span className="mk-mono">secure</span>,{" "}
                    <span className="mk-mono">sameSite: lax</span>, path{" "}
                    <span className="mk-mono">/</span>, and a max age of 365 days. Because
                    it is httpOnly, no script on the page can read it.
                  </p>
                </div>
                <div className="mk-card">
                  <p className="mk-label">gh_oauth_state</p>
                  <p className="mk-body" style={{ margin: "10px 0 0", fontSize: "var(--t-body)" }}>
                    The one-shot value that ties your sign-in redirect back to the request
                    that started it, so a forged callback is rejected. Deleted the moment
                    the sign-in completes.
                  </p>
                </div>
              </div>
              <Ref>
                dashboard/app/api/auth/github/callback/route.ts:19, 34-36, 106-113;
                dashboard/lib/api.ts:26, 38-43
              </Ref>
              <p className="mk-body" style={{ marginTop: 18 }}>
                There is no consent banner because there is nothing to consent to. Your
                theme choice is kept in your own browser&rsquo;s local storage and is never
                sent anywhere.
              </p>
              <Ref>dashboard/app/layout.tsx:20-21</Ref>

              <h2 className="mk-h2" style={{ marginTop: 48 }}>
                Analytics and third-party scripts
              </h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                There are none. No product analytics, no tag manager, no session recorder,
                no heat maps, no error reporting service, no advertising or conversion
                pixel. The site&rsquo;s entire runtime dependency list is Next.js, React
                and one font package.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Two inline scripts run, both first-party and both inspectable in page
                source: one line that applies your stored theme before the first paint so
                the page does not flash the wrong colours, and a block of{" "}
                <span className="mk-mono">application/ld+json</span> structured data on the
                homepage that describes the product to search engines. The typeface is
                fetched at build time and served from this domain, so loading a page here
                sends no request to Google Fonts or to any other font host.
              </p>
              <Ref>
                dashboard/package.json:12-17; dashboard/app/layout.tsx:2-6, 20-21, 226-230;
                dashboard/app/page.tsx:105-112
              </Ref>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Who else touches the data</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Three companies, and only these three. Each one is named because it is in
                the deployment, not because a template suggested it.
              </p>
              <div className="mk-grid" style={{ marginTop: 18 }}>
                <div className="mk-card">
                  <p className="mk-h3">Vercel</p>
                  <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-body)" }}>
                    Hosts both halves of this site: the dashboard you are reading and the
                    control-plane API behind it. Everything described on this page passes
                    through their infrastructure.
                  </p>
                  <Ref>api/vercel.json; deploy/README-dashboard.md:3, 11-12</Ref>
                </div>
                <div className="mk-card">
                  <p className="mk-h3">Neon</p>
                  <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-body)" }}>
                    The Postgres database. Playground sandboxes, accounts, traces, findings
                    and the audit chain all live here.
                  </p>
                  <Ref>deploy/README-dashboard.md:3, 58-80</Ref>
                </div>
                <div className="mk-card">
                  <p className="mk-h3">GitHub</p>
                  <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-body)" }}>
                    Only if you sign in. The sign-in exchange and the profile lookup go to{" "}
                    <span className="mk-mono">github.com</span> and{" "}
                    <span className="mk-mono">api.github.com</span>, and later repository
                    listings and scans do too. A visitor who never signs in never causes a
                    request to GitHub.
                  </p>
                  <Ref>
                    dashboard/app/api/auth/github/callback/route.ts:46, 64-68;
                    src/agentfox/apps/gateway/routes/integrations.py:57
                  </Ref>
                </div>
              </div>
              <p className="mk-body" style={{ marginTop: 18 }}>
                The software can be configured to reach other destinations, for example a
                model provider, an outbound findings webhook, or an observability vendor
                such as LangSmith or Langfuse. Every one of those is off unless an operator
                turns it on, and all of them sit behind a single switch that ships in the
                off position. This deployment is a demonstration running on the offline
                provider, so none of those destinations is in use for anything described
                above.
              </p>
              <Ref>
                src/agentfox/core/config.py:117-119, 173-181, 360-398; agentfox.toml:13-14;
                src/agentfox/core/webhooks.py:97
              </Ref>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">What the audit log keeps about detected data</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                This one deserves saying out loud, because the obvious implementation is a
                bad one. AgentFox detects secrets and personal data in agent traffic. If it
                stored what it found, the audit log would become exactly the honeypot
                customers are afraid of: a single table containing every card number and
                national insurance number that ever passed through.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                So it does not. When a detector matches, what is written is the entity type,
                a confidence score, the start and end offsets of the match, and a sample
                that keeps the first four characters and masks the rest, capped at 80
                characters. Four characters is enough for a human reviewing a finding to
                recognise what kind of thing matched. It is not enough to be the value.
              </p>
              <Ref>
                src/agentfox/capabilities/detection/base.py:204-218;
                src/agentfox/capabilities/detection/detectors/pii.py:133; src/agentfox/core/models/:486-502
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Separately, before anything reaches the audit chain, values under keys that
                look sensitive (password, secret, token, api_key, authorization,
                credential, private key, access key, ssn) are replaced with{" "}
                <span className="mk-mono">&lt;redacted&gt;</span>, and long strings are
                truncated. The chain stores structure and decisions, not content.
              </p>
              <Ref>src/agentfox/platform/ledger/chain.py:67-107</Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The cost of that design, stated rather than hidden: there is no update or
                delete path for an audit entry anywhere in the codebase. That is what makes
                the chain worth verifying, and it is also why erasing an account is a
                manual operation rather than a button. See below.
              </p>
              <Ref>src/agentfox/platform/ledger/chain.py:12-19</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Getting your data deleted</h2>
              <div className="mk-steps" style={{ marginTop: 20 }}>
                <div className="mk-step">
                  <span className="mk-step-n">1</span>
                  <div>
                    <p className="mk-h3">A playground sandbox</p>
                    <p className="mk-body" style={{ margin: "6px 0 0" }}>
                      Do nothing. Close the tab and it deletes itself thirty minutes later,
                      rows and all. If you want it gone sooner, write to the address below
                      with the sandbox id.
                    </p>
                  </div>
                </div>
                <div className="mk-step">
                  <span className="mk-step-n">2</span>
                  <div>
                    <p className="mk-h3">An account</p>
                    <p className="mk-body" style={{ margin: "6px 0 0" }}>
                      Write to <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a> from
                      the address on the account, or open an issue from the GitHub account
                      you signed in with. There is no self-service delete endpoint in the
                      code today, so this is a person doing it by hand, which also means it
                      is not instant. You will get a reply saying what was removed.
                    </p>
                  </div>
                </div>
                <div className="mk-step">
                  <span className="mk-step-n">3</span>
                  <div>
                    <p className="mk-h3">Just the GitHub connection</p>
                    <p className="mk-body" style={{ margin: "6px 0 0" }}>
                      Revoking the authorisation in your GitHub settings invalidates the
                      stored token immediately, at GitHub&rsquo;s end, without waiting for
                      us.
                    </p>
                  </div>
                </div>
              </div>
              <p className="mk-body" style={{ marginTop: 22 }}>
                Questions about any of this go to the same address:{" "}
                <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>. It is read by the
                maintainer, who is one person.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <div className="mk-card mk-card-raised">
                <span className="mk-eyebrow">The part that matters most</span>
                <h2 className="mk-h2" style={{ marginTop: 16 }}>
                  A copy you run yourself sends us nothing</h2>
                <p className="mk-body" style={{ marginTop: 14 }}>
                  Nothing on this page applies to a self-hosted install. There is no
                  licence check, no activation call, no usage ping, no crash reporter and
                  no telemetry of any kind, because none of that code exists to be turned
                  off. Your agents&rsquo; traffic, your policies, your findings and your
                  audit chain stay in your database, and we never see that they exist.
                </p>
                <p className="mk-body" style={{ marginTop: 14 }}>
                  Outbound network access is one setting and it ships off. With it off, a
                  configured webhook URL sends nothing and a configured model provider is
                  not called. The default provider is the offline one, which is why the
                  whole system is demonstrable with a single{" "}
                  <span className="mk-mono">docker compose up</span> and no account
                  anywhere.
                </p>
                <Ref>
                  src/agentfox/core/config.py:117-119, 360-363; agentfox.toml:13-14;
                  src/agentfox/core/webhooks.py:97; src/agentfox/platform/providers/echo.py:1-6
                </Ref>
                <p className="mk-body" style={{ marginTop: 14 }}>
                  This is unusual enough to be worth checking rather than believing. The{" "}
                  <a href={SRC} target="_blank" rel="noreferrer">
                    source is public
                  </a>
                  , the setting is one grep, and the licence permits you to fork it if you
                  ever disagree with what it does.
                </p>
              </div>
              <p className="mk-fine" style={{ marginTop: 26 }}>
                Also here: <Link href="/terms">terms</Link>,{" "}
                <Link href="/security">security</Link>, <Link href="/legal">legal</Link>.
              </p>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
