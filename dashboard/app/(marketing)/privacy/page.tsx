import type { Metadata } from "next";
import Link from "next/link";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { publicPageMetadata, REPO_URL, SUPPORT_EMAIL } from "@/lib/site";

export const dynamic = "force-dynamic";

/**
 * Every sentence on this page is a statement about code in this repository or about
 * how the hosted deployment is configured, and the code is named beside it wherever a
 * reader might reasonably want to check. A privacy policy for a security product that
 * cannot be checked is worth nothing.
 *
 * Deliberately absent: a retention period nobody implemented, a sub-processor that is
 * not in the deployment, a transfer safeguard nobody has signed, and the phrase
 * "industry-standard encryption". When the deployment changes (a provider added, a
 * judge switched on or off), this page changes in the same pull request.
 */
export const metadata: Metadata = publicPageMetadata({
  title: "Privacy policy",
  description:
    "What the hosted playground, sign-in and waitlist store, for how long, which companies process it, the AI that reads what you send, your rights, and why a copy you run yourself sends us nothing.",
  path: "/privacy",
});

const SRC = `${REPO_URL}/blob/main`;
const MAIL = `mailto:${SUPPORT_EMAIL}`;

/**
 * A source citation under a claim.
 *
 * `overflowWrap: anywhere` is load-bearing, not decoration. A path like
 * `dashboard/app/api/auth/github/callback/route.ts:97-103` is a single unbroken token
 * wider than a 375px viewport&rsquo;s content column, so without it the narrowest
 * phone gets a horizontal scrollbar on a page about trustworthiness.
 */
function Ref({ children }: { children: React.ReactNode }) {
  // The files, not their line numbers: line numbers go stale with every edit and
  // read as noise to anyone who is not about to open the file.
  const files = Array.from(
    new Set(
      String(Array.isArray(children) ? children.join("") : children)
        .split(/[;\n]/)
        .map((s) => s.replace(/:[\d\s,–-]*$/, "").trim())
        .filter(Boolean),
    ),
  );
  return (
    <p className="mk-mono" style={{ color: "var(--mk-muted)", margin: "10px 0 0", overflowWrap: "anywhere" }}>
      Source: {files.join(", ")}
    </p>
  );
}

/** A name and what it is, as a card. Used for cookies and for the companies list. */
function Entry({ name, children, mono = false }: { name: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="mk-card">
      <p className={mono ? "mk-label" : "mk-h3"}>{name}</p>
      <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-body)" }}>
        {children}
      </p>
    </div>
  );
}

export default function Privacy() {
  return (
    <div className="mk">
      <MarketingNav />
      <main className="mk-prose">
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <span className="mk-eyebrow">Privacy</span>
              <h1 className="mk-h1" style={{ margin: "18px 0 0" }}>
                Privacy policy</h1>
              <p className="mk-lede" style={{ marginTop: 20 }}>
                What this site stores if you use the playground, sign in or join the
                pricing list, who processes it, and how to get it deleted. A copy you run
                yourself sends us nothing.
              </p>
              <p className="mk-fine" style={{ marginTop: 16 }}>
                Last updated 9 November 2026.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Who we are</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The hosted service at this domain is run by Nometria Inc., a Delaware
                corporation. For the personal data described here, Nometria Inc. is the
                controller under the EU and UK GDPR, the business under California law, and
                the data fiduciary under India&rsquo;s Digital Personal Data Protection Act.
                Questions, requests and complaints go to{" "}
                <a href={MAIL}>{SUPPORT_EMAIL}</a>.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The service is a developer tool for people building AI agents, usually on
                behalf of a company. It is not directed to children: see{" "}
                <a href="#children">children</a> below.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">The playground</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The playground needs no account. It asks for no email address, no name and
                no payment details, and it has nowhere to put them. When you send your
                first message, the server creates a sandbox and hands you its id: 128 bits
                from a cryptographic random source. That id is the sandbox&rsquo;s tenant
                key and it is the only credential in the playground. It identifies no
                person.
              </p>
              <Ref>src/agentfox/apps/gateway/playground_sessions.py; src/agentfox/apps/gateway/routes/playground.py</Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                What goes into a sandbox
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                The messages you type and the &ldquo;retrieved document&rdquo; you are
                invited to edit are sent to the server and written into your sandbox,
                verbatim, as conversation turns alongside the traces, decisions and
                findings your attacks produce. If you paste something into the playground,
                it is stored, and it is read by the checks described under{" "}
                <a href="#ai">AI that reads what you send</a>. Do not paste personal data.
              </p>
              <Ref>
                src/agentfox/apps/gateway/routes/playground.py; src/agentfox/capabilities/containment/escalation.py
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Every one of those rows is written under an{" "}
                <span className="mk-mono">org_id</span> that is your sandbox id, so the
                same session-level tenant filter that separates two customers is what
                separates your sandbox from everyone else&rsquo;s.
              </p>
              <Ref>src/agentfox/core/tenancy.py</Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                How long it lives
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Thirty minutes of idle time. The clock restarts on every action, so it is
                thirty minutes since your last request, not since you arrived. After that
                the sandbox can no longer be opened, and every row belonging to it is
                deleted from every table, audit entries included, by the next sweep. A
                sweep runs when a new sandbox is created and at least once a day, so an
                expired sandbox is gone within a day at the latest. A sandbox is also
                dropped early, oldest idle one first, if more than 200 are live across the
                whole deployment.
              </p>
              <Ref>
                src/agentfox/apps/gateway/playground_sessions.py; src/agentfox/apps/gateway/routes/jobs.py; api/vercel.json
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Two things follow from the id being the only credential. Anyone you send
                your sandbox link to can read that sandbox. And the id cannot be revoked
                before it expires.
              </p>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                Your IP address
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Our code uses it only as the key for per-address rate limits (sandboxes
                created, pricing-list signups, and requests to the live page), held in the
                server process&rsquo;s memory for up to an hour. It is not written to
                our database. Our hosting providers, like any web host, record request
                addresses in their own access logs, which they keep under their own terms.
              </p>
              <Ref>src/agentfox/apps/gateway/client_address.py; src/agentfox/apps/gateway/playground_sessions.py; src/agentfox/apps/gateway/routes/waitlist.py; src/agentfox/apps/gateway/routes/probes.py</Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                The agent&rsquo;s replies
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                The agent you attack is not a language model: its replies come from the
                offline provider, which is deterministic and network-free, and the seeded{" "}
                <span className="mk-mono">payments.transfer</span> and{" "}
                <span className="mk-mono">email.send</span> tools have no backend behind
                them. If a message says you might harm yourself, the agent answers with
                where to find a crisis line instead.
              </p>
              <Ref>src/agentfox/platform/providers/echo.py; src/agentfox/apps/gateway/routes/playground.py</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Signing in</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                You sign in with GitHub, Google or Microsoft. There is no password. Signing
                in creates a real account and a workspace with you as its owner. The same
                person signing in with two providers gets two separate workspaces, because
                accounts are matched on the provider&rsquo;s own id, never on an email
                address.
              </p>
              <Ref>src/agentfox/apps/gateway/routes/integrations.py</Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                What is stored about you
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Your name and email address as the provider reports them, and the
                provider&rsquo;s id for you (GitHub&rsquo;s numeric user id, or the OpenID
                subject from Google or Microsoft). With GitHub, if your email is private,
                the primary address from GitHub&rsquo;s email endpoint is used, and failing
                that your <span className="mk-mono">users.noreply.github.com</span>{" "}
                address. That is the whole user record: no profile, no phone number and no
                billing row. What you then put into your workspace (agents, policies,
                traces of your agents&rsquo; traffic, findings) is stored in it.
              </p>
              <Ref>
                dashboard/app/api/auth/github/callback/route.ts; dashboard/app/api/auth/[provider]/callback/route.ts; src/agentfox/core/models/identity.py
              </Ref>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>
                What we ask the provider for
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Google and Microsoft: <span className="mk-mono">openid email profile</span>,
                which is who you are and nothing else. GitHub:{" "}
                <span className="mk-mono">user:email</span> for your address, and{" "}
                <span className="mk-mono">repo</span>, because GitHub sign-in doubles as
                the grant that lets AgentFox list and scan your repositories, private ones
                included. GitHub has no read-only version of that scope, so it also
                technically permits writes. AgentFox only reads: a repository scan is
                static, and nothing in the scanner writes to GitHub or runs the code it
                reads.
              </p>
              <Ref>
                dashboard/lib/product/oauth.ts; dashboard/app/api/auth/github/login/route.ts; src/agentfox/apps/gateway/routes/integrations.py
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The GitHub access token is stored, encrypted with Fernet under a key held
                in the deployment&rsquo;s environment rather than in the database. If that
                key is not configured, the request fails rather than storing the token in
                the clear. The raw token never reaches your browser. Google and Microsoft
                tokens are used once to read who you are and are not stored.
              </p>
              <Ref>src/agentfox/apps/gateway/routes/integrations.py; src/agentfox/core/models/identity.py</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">The pricing list</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The form on the pricing page asks for one thing, an email address, and
                stores it with the date and which form it came from. It is used for one
                email when pricing is announced. Nothing is sent when you join, and the
                address is not passed to a mailing service or anyone else. It is kept until
                you ask us to remove it.
              </p>
              <Ref>dashboard/components/marketing/waitlist.tsx; src/agentfox/apps/gateway/routes/waitlist.py</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section" id="ai">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">AI that reads what you send</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                AgentFox&rsquo;s job is to check text: playground messages, and the agent
                traffic you send to your workspace. On the hosted service those checks are
                made in three places.
              </p>
              <div className="mk-grid" style={{ marginTop: 18 }}>
                <Entry name="Rules and detectors in our own process">
                  Pattern rules and the personal-data and secret detectors run inside the
                  API itself. Nothing leaves.
                </Entry>
                <Entry name="Classifier models on our model server">
                  The prompt-injection classifier and similar models run on a model server
                  we operate, which the API calls over an authenticated connection.
                </Entry>
                <Entry name="Hosted judges: Anthropic and TypeSafe">
                  Some checks ask a hosted model a question about the text: an LLM from
                  Anthropic, and TypeSafe&rsquo;s Jev. Before anything is sent, the
                  personal data our local detectors find is masked; if that redaction
                  cannot run, nothing is sent. Redaction only masks what the detectors
                  find, so do not rely on it for data you would not want a third party to
                  see. These providers process the text under their own API terms.
                </Entry>
              </div>
              <Ref>
                src/agentfox/core/config.py; src/agentfox/capabilities/judgment/egress.py; src/agentfox/capabilities/judgment/llm.py; src/agentfox/capabilities/judgment/jev.py; deploy/model-server/README.md
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                No AI makes a decision about you as a person. The checks decide whether a
                piece of agent traffic is allowed, and you can see every verdict.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Cookies and local storage</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Every cookie here is set by this site, is needed for the feature it
                belongs to, and is read by nobody else. There is no consent banner because
                there is nothing optional to consent to.
              </p>
              <div className="mk-grid mk-grid-2" style={{ marginTop: 18 }}>
                <Entry mono name="agentfox_session">
                  Keeps you signed in: the API token minted at sign-in. httpOnly, secure,
                  same-site, 365 days, and revoked when you sign out.
                </Entry>
                <Entry mono name="gh_oauth_state, google_oauth_state, microsoft_oauth_state">
                  A one-time value that ties a sign-in redirect back to the request that
                  started it, so a forged callback is refused. Ten minutes at most, deleted
                  when sign-in completes.
                </Entry>
                <Entry mono name="agentfox_project, agentfox_map_project">
                  Which project you were last looking at in the app. One year.
                </Entry>
                <Entry mono name="agentfox_setup_skipped">
                  That you skipped the add-a-project step, so it is not shown again. One
                  year.
                </Entry>
              </div>
              <Ref>
                dashboard/app/api/auth/github/login/route.ts; dashboard/app/api/auth/[provider]/login/route.ts; dashboard/lib/product/api.ts; dashboard/lib/product/project.ts; dashboard/middleware.ts
              </Ref>
              <p className="mk-body" style={{ marginTop: 18 }}>
                Your browser&rsquo;s local storage keeps your theme choice and when you
                dismissed a setup banner in the app. Neither is sent anywhere.
              </p>
              <Ref>dashboard/components/ui/ThemeToggle.tsx; dashboard/components/product/SetupBanner.tsx</Ref>

              <h2 className="mk-h2" style={{ marginTop: 48 }}>
                Analytics and third-party scripts
              </h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                There are none. No product analytics, no tag manager, no session recorder,
                no heat maps, no error reporting service, no advertising or conversion
                pixel. The typeface is fetched at build time and served from this domain,
                so loading a page here sends no request to Google Fonts or to any other
                font host. The only inline scripts are first-party: one line that applies
                your stored theme before the first paint, and structured data that
                describes the product to search engines.
              </p>
              <Ref>dashboard/package.json; dashboard/app/layout.tsx; dashboard/app/page.tsx</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Who else processes the data</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Each is named because it is in the deployment, not because a template
                suggested it. We do not sell personal data, and we do not share it for
                advertising.
              </p>
              <div className="mk-grid mk-grid-2" style={{ marginTop: 18 }}>
                <Entry name="Render">
                  Hosts the website and dashboard you are reading, in the United States.
                </Entry>
                <Entry name="Vercel">
                  Hosts the API behind it, which every request on this page passes through.
                </Entry>
                <Entry name="Neon">
                  The Postgres database: sandboxes, accounts, workspaces, the pricing list
                  and the audit chain.
                </Entry>
                <Entry name="Anthropic and TypeSafe">
                  The hosted judges described above, for redacted text only.
                </Entry>
                <Entry name="GitHub, Google, Microsoft">
                  Only the one you sign in with, which tells us who you are. GitHub also
                  serves the repository listings and scans you ask for. A visitor who never
                  signs in never causes a request to any of them.
                </Entry>
              </div>
              <Ref>deploy/render.yaml; api/vercel.json; deploy/README-dashboard.md; dashboard/lib/product/oauth.ts</Ref>
              <p className="mk-body" style={{ marginTop: 18 }}>
                Render and Vercel run the service in the United States. If you use it from
                elsewhere, your data is transferred to and processed in the United States.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                We would disclose data to anyone else only if the law required it.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">What the audit log keeps about detected data</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                AgentFox detects secrets and personal data in agent traffic. If it stored
                what it found, the audit log would become exactly the honeypot customers
                are afraid of. So it does not. When a detector matches, what is written is
                the entity type, a confidence score, the start and end offsets of the
                match, and a sample that keeps the first four characters and masks the
                rest, capped at 80 characters.
              </p>
              <Ref>
                src/agentfox/capabilities/detection/base.py; src/agentfox/capabilities/detection/detectors/pii.py
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Before anything reaches the audit chain, values under keys that look
                sensitive (password, secret, token, api_key, authorization, credential,
                private key, access key, ssn) are replaced with{" "}
                <span className="mk-mono">&lt;redacted&gt;</span>, and long strings are
                truncated. Entries are never edited. The only ways they are removed are a
                playground sandbox expiring and an owner deleting their workspace, which
                takes that workspace&rsquo;s whole chain with it.
              </p>
              <Ref>src/agentfox/platform/ledger/chain.py; src/agentfox/core/tenancy.py</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">How long it is kept</h2>
              <ul className="mk-body" style={{ marginTop: 14, paddingLeft: 20, display: "grid", gap: 8 }}>
                <li>A playground sandbox: until 30 minutes after your last action, then deleted within a day.</li>
                <li>
                  Your account and workspace: until you delete them. A workspace owner can also
                  set how long traces and other records are kept, in Settings, Retention.
                </li>
                <li>Your address on the pricing list: until you ask us to remove it.</li>
                <li>Your IP address in our code: one hour, in memory only.</li>
              </ul>
              <Ref>src/agentfox/capabilities/compliance/retention.py</Ref>

              <h2 className="mk-h2" style={{ marginTop: 48 }}>Getting your data deleted</h2>
              <div className="mk-steps" style={{ marginTop: 20 }}>
                <div className="mk-step">
                  <span className="mk-step-n">1</span>
                  <div>
                    <p className="mk-h3">Your account and workspace</p>
                    <p className="mk-body" style={{ margin: "6px 0 0" }}>
                      Settings, Retention, <b>Delete my account</b>, then type your email to
                      confirm. Your account and every row in the workspace go at once:
                      agents, policies, traces, findings, keys, the stored GitHub token and
                      the audit chain. It is refused while a legal hold you placed is
                      active, or while another member remains; in that case, or if you
                      cannot sign in, write to <a href={MAIL}>{SUPPORT_EMAIL}</a> from the
                      address on the account.
                    </p>
                  </div>
                </div>
                <div className="mk-step">
                  <span className="mk-step-n">2</span>
                  <div>
                    <p className="mk-h3">The GitHub grant</p>
                    <p className="mk-body" style={{ margin: "6px 0 0" }}>
                      Revoke AgentFox in your GitHub settings, under Applications. That
                      invalidates the token at GitHub&rsquo;s end immediately.
                    </p>
                  </div>
                </div>
                <div className="mk-step">
                  <span className="mk-step-n">3</span>
                  <div>
                    <p className="mk-h3">A playground sandbox, or the pricing list</p>
                    <p className="mk-body" style={{ margin: "6px 0 0" }}>
                      A sandbox deletes itself. To have one removed sooner, or your address
                      taken off the pricing list, write to{" "}
                      <a href={MAIL}>{SUPPORT_EMAIL}</a> with the sandbox id or the address.
                    </p>
                  </div>
                </div>
              </div>
              <Ref>src/agentfox/apps/gateway/routes/integrations.py; dashboard/components/product/Retention.tsx</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band" id="rights">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Your rights</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Wherever you are, you can ask what we hold about you, ask for a copy, ask
                us to correct it, and ask us to delete it. Write to{" "}
                <a href={MAIL}>{SUPPORT_EMAIL}</a>; we will need to confirm the request
                comes from you, usually by a reply from the address on the account. You
                will not be treated differently for asking.
              </p>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>EU and UK</h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Our legal bases: running the service you signed up for (your account and
                workspace); our legitimate interest in offering a public demonstration
                and keeping it safe from abuse (the playground, the rate limit, the
                checks on what you send); and your consent for the pricing list, which you
                can withdraw at any time. You also have the rights to restrict or object to
                processing and to data portability, and to complain to your data
                protection authority (in the UK, the ICO).
              </p>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>California</h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                In the last twelve months we have collected identifiers (name, email
                address, sign-in provider id, IP address) and the content you send to the
                playground or your workspace, from you and from the sign-in provider you
                chose, for the purposes on this page. We do not sell or share personal
                information, and we do not use sensitive personal information to infer
                anything about you. You have the rights to know, delete and correct.
              </p>

              <h3 className="mk-h3" style={{ marginTop: 30 }}>India</h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Under the Digital Personal Data Protection Act you can ask for a summary of
                your data and how it is processed, have it corrected or erased, nominate
                someone to exercise these rights for you, and raise a grievance. Grievances
                go to <a href={MAIL}>{SUPPORT_EMAIL}</a>; if you are not satisfied with the
                answer, you can complain to the Data Protection Board of India.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section" id="children">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Children</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The service is not directed to children, and accounts are for people aged
                18 or over. We do not knowingly collect data from anyone under 13, or under
                16 in the European Economic Area. If you believe a child has given us
                personal data, write to <a href={MAIL}>{SUPPORT_EMAIL}</a> and we will delete
                it.
              </p>

              <h2 className="mk-h2" style={{ marginTop: 48 }}>Changes</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The date at the top is when this page last changed. It lives in the public
                repository, so every past version and the reason for each change can be
                read there.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
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
                  configured webhook URL sends nothing and no hosted model or judge is
                  called. The default provider is the offline one, which is why the whole
                  system is demonstrable with a single{" "}
                  <span className="mk-mono">docker compose up</span> and no account
                  anywhere.
                </p>
                <Ref>
                  src/agentfox/core/config.py; agentfox.toml; src/agentfox/core/webhooks.py; src/agentfox/platform/providers/echo.py
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
                <Link href="/security">security</Link>.
              </p>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
