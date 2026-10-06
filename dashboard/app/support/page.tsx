import type { CSSProperties } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { publicPageMetadata, SUPPORT_EMAIL } from "@/lib/site";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";

export const dynamic = "force-dynamic";

/**
 * How to get help, scoped to what one maintainer can actually promise.
 *
 * The routing below is copied from the files that define it, not written for this
 * page: `.github/ISSUE_TEMPLATE/{bug_report,wrong_verdict,feature_request}.yml` for
 * the three forms and the fields each one asks for, `config.yml` for the contact
 * links (blank issues are disabled, so those four entries are the whole menu), and
 * SECURITY.md for the vulnerability route.
 *
 * SECURITY.md's process is linked and deliberately not restated. One copy of a
 * disclosure process is a process; two copies is a chance for the wrong one to be
 * followed, and the wrong one here means a vulnerability filed in public.
 *
 * No response time appears anywhere on this page. SECURITY.md states its own aim
 * for advisories and that is the only place a timing commitment belongs.
 */

export const metadata: Metadata = publicPageMetadata({
  title: "Support and how to get help",
  description:
    "Which issue template to use, where questions go, the private route for a vulnerability, and what one maintainer can honestly promise.",
  path: "/support",
});

const REPO = "https://github.com/architsharm/agentfox";
const SECURITY_MD = `${REPO}/blob/main/SECURITY.md`;
const DISCUSSIONS = `${REPO}/discussions`;
const NEW_ISSUE = `${REPO}/issues/new/choose`;
const GETTING_STARTED = `${REPO}/blob/main/docs/getting-started.md`;
const HARNESS = `${REPO}/tree/main/harness`;

function Out({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

function Head({ eyebrow, title, lede }: { eyebrow: string; title: string; lede?: string }) {
  return (
    <div className="mk-narrow mk-up">
      <span className="mk-eyebrow">{eyebrow}</span>
      <h2 className="mk-h2" style={{ marginTop: 14 }}>
        {title}
      </h2>
      {lede && (
        <p className="mk-lede" style={{ marginTop: 14 }}>
          {lede}
        </p>
      )}
    </div>
  );
}

const SCROLLER: CSSProperties = { padding: 0, overflowX: "auto" };
const TABLE: CSSProperties = {
  width: "100%",
  minWidth: 620,
  borderCollapse: "collapse",
  fontSize: "var(--t-small)",
};
const TH: CSSProperties = {
  padding: "12px 14px",
  borderBottom: "1px solid var(--mk-border-strong)",
  verticalAlign: "bottom",
  fontWeight: 600,
};
const TD: CSSProperties = {
  padding: "11px 14px",
  borderBottom: "1px solid var(--mk-border)",
  verticalAlign: "top",
  color: "var(--mk-muted)",
};
const TD_HEAD: CSSProperties = { ...TD, color: "var(--mk-text)", fontWeight: 500 };

/* --- Routing ------------------------------------------------------------ */

const ROUTES: [string, string, string][] = [
  [
    "It crashed, hung, or contradicted the docs",
    "Bug report",
    "Command and output, version, how you run it, Python and OS, extras.",
  ],
  [
    "It blocked something legitimate",
    "Wrong verdict",
    "Trace id, rule id, pack and mode, the surface, what the decision said.",
  ],
  [
    "It allowed something it should have stopped",
    "Wrong verdict",
    "Same fields. A detector missing an injection belongs here, not in an advisory.",
  ],
  [
    "The product cannot do a thing you need",
    "Feature request",
    "What you were governing and where it ran out of road.",
  ],
  [
    "How do I, is this the right tool, does this design hold",
    "Discussions",
    "Questions and ideas, so the issue tracker stays a list of fixes.",
  ],
  [
    "You found a vulnerability",
    "SECURITY.md, privately",
    "Never a public issue. The route is in SECURITY.md and only there.",
  ],
];

const DOCS: { title: string; body: React.ReactNode }[] = [
  {
    title: "A linear first hour",
    body: (
      <>
        <Out href={GETTING_STARTED}>docs/getting-started.md</Out> goes from an empty directory to
        one of your own agents under enforcement. Every command in it was run first.
      </>
    ),
  },
  {
    title: "What the thing actually does",
    body: (
      <>
        <Link href="/how-it-works">How it works</Link> is the public explanation.{" "}
        <Link href="/product">The product page</Link> walks each layer on a real screen.
      </>
    ),
  },
  {
    title: "The vocabulary",
    body: (
      <>
        The <Link href="/app/glossary">glossary</Link> defines provenance, impact tiers, grants and
        the rest. It lives inside the dashboard, so it asks you to sign in.
      </>
    ),
  },
  {
    title: "Let a coding agent drive it",
    body: (
      <>
        The <Out href={HARNESS}>harness</Out> packages the product as skills, commands, subagents
        and safety hooks, so an agent can do the setup without learning 13 CLI commands and their subcommands.
      </>
    ),
  },
];

export default function Support() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <h1 className="mk-h1 mk-up mk-d1">
              Support</h1>
            <p className="mk-lede mk-up mk-d2" style={{ marginTop: 20 }}>
              One person reads these. There is no promised reply time.
            </p>
            <div className="mk-row mk-up mk-d3" style={{ marginTop: 26, gap: 10 }}>
              <a href={NEW_ISSUE} target="_blank" rel="noreferrer" className="mk-btn mk-btn-primary">
                Open an issue
              </a>
              <a href={DISCUSSIONS} target="_blank" rel="noreferrer" className="mk-btn mk-btn-outline">
                Ask in Discussions
              </a>
            </div>
          </div>
        </section>

        {/* 1. Before you file */}
        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="Before you file"
              title="Redact first"
              lede="A report for this product is likely to contain production data, and a GitHub issue is public."
            />
            <div className="mk-narrow" style={{ marginTop: 36 }}>
              <div
                className="mk-card mk-up"
                style={{
                  borderColor: "var(--mk-stop)",
                  background: "var(--mk-stop-soft)",
                  display: "grid",
                  gap: 8 }}
              >
                <span className="mk-label" style={{ color: "var(--mk-stop)" }}>
                  Redact first
                </span>
                <p className="mk-body" style={{ margin: 0, fontSize: "var(--t-small)", color: "var(--mk-text)" }}>
                  Do not paste real prompts, tool arguments, retrieved documents or audit rows. Replace names, accounts, URLs and secrets with obvious placeholders. A reduced reproduction with made-up values runs here.{" "}
                  <Link href="/docs/support">The commands to run first are in the docs.</Link>
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* 2. Routing table */}
        <section className="mk-section mk-band mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="Where it goes"
              title="Which template, for which problem"
              lede="Blank issues are switched off, so the form you pick asks the right questions."
            />
            <div className="mk-card mk-up mk-d2" style={{ ...SCROLLER, marginTop: 36 }}>
              <table style={TABLE}>
                <thead>
                  <tr>
                    <th style={TH}>What happened</th>
                    <th style={TH}>Where it goes</th>
                    <th style={TH}>What it asks for</th>
                  </tr>
                </thead>
                <tbody>
                  {ROUTES.map(([what, where, asks]) => (
                    <tr key={what}>
                      <td style={TD_HEAD}>{what}</td>
                      <td style={TD}>{where}</td>
                      <td style={TD}>{asks}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 3. Wrong verdict, called out */}
        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="The one that matters most"
              title="A wrong verdict is the best report we get"
              lede="A false positive costs you an afternoon. A false negative is the thing the product exists to prevent. There is a template for both."
            />
            <p className="mk-fine" style={{ marginTop: 18 }}>
              The trace id and the rule id are what is needed, not the payload. Redact it and
              keep the structure.
            </p>
            <div className="mk-grid mk-grid-3" style={{ marginTop: 36 }}>
              <div className="mk-card">
                <span className="mk-label">It asks for</span>
                <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-small)" }}>
                  Which way it went wrong, the trace id, the rule id, the policy pack and its
                  mode, and which surface was being checked: input, output, tool arguments, tool
                  result, a memory write or an agent message.
                </p>
              </div>
              <div className="mk-card">
                <span className="mk-label">And if a tool was involved</span>
                <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-small)" }}>
                  The tool&rsquo;s impact tier and the capability grant that applied. Containment is
                  exactly as good as the declarations behind it.
                </p>
              </div>
              <div className="mk-card">
                <span className="mk-label">Not a vulnerability</span>
                <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-small)" }}>
                  A prompt injection a detector missed goes here, not through the private advisory
                  route. SECURITY.md says so itself: detection is a speed bump, not a defence.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band mk-reveal">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Found a vulnerability?</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Do not open a public issue for a security problem, and do not email the details.{" "}
                <Out href={SECURITY_MD}>SECURITY.md</Out> holds the private reporting route, what
                is in scope, and the two things this project says in public are not
                vulnerabilities.
              </p>
              <p className="mk-fine" style={{ marginTop: 14 }}>
                It is the only description of that process, deliberately.
              </p>
              <div className="mk-row" style={{ marginTop: 20 }}>
                <a
                  href={SECURITY_MD}
                  target="_blank"
                  rel="noreferrer"
                  className="mk-btn mk-btn-outline"
                >
                  Read SECURITY.md
                </a>
              </div>
            </div>
          </div>
        </section>

        {/* 5. Commercial */}
        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="Commercial support"
              title="A named person to call"
              lede="The identical software, plus help with rollout and priority on fixes. Not priced yet."
            />
            <div className="mk-grid mk-grid-3" style={{ marginTop: 40 }}>
              <div className="mk-card mk-up mk-d1" style={{ display: "grid", gap: 8, minWidth: 0 }}>
                <span className="mk-label">Free tier</span>
                <p className="mk-body" style={{ margin: 0, fontSize: "var(--t-small)" }}>
                  GitHub Issues and Discussions, answered on a best-effort basis by one developer.
                  No service level, and no promised response time.
                </p>
              </div>
              <div className="mk-card mk-up mk-d2" style={{ display: "grid", gap: 8, minWidth: 0 }}>
                <span className="mk-label">Supported self-hosted</span>
                <p className="mk-body" style={{ margin: 0, fontSize: "var(--t-small)" }}>
                  A support relationship, not different software. Email{" "}
                  <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a> and say what you are
                  rolling out.
                </p>
              </div>
              <div className="mk-card mk-up mk-d3" style={{ display: "grid", gap: 8, minWidth: 0 }}>
                <span className="mk-label">Managed cloud</span>
                <p className="mk-body" style={{ margin: 0, fontSize: "var(--t-small)" }}>
                  Open and free while in preview: sign in with GitHub, no card. Editions are on{" "}
                  <Link href="/pricing">the pricing page</Link>.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* 6. Docs */}
        <section className="mk-section mk-band mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="Read first"
              title="Where the documentation lives"
              lede="Most questions have an answer in one of these four."
            />
            <div className="mk-grid mk-grid-4" style={{ marginTop: 40 }}>
              {DOCS.map((d, i) => (
                <div key={d.title} className={`mk-card mk-up mk-d${Math.min(i + 1, 5)}`}>
                  <h3 className="mk-h3">{d.title}</h3>
                  <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-small)" }}>
                    {d.body}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
