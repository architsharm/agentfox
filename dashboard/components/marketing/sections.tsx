import Link from "next/link";

import { FLAT, PRODUCT, RESOURCES, SECONDARY } from "@/lib/nav";
import { BrandLockup } from "@/components/marketing/brand";

/**
 * The lower half of the public landing page: what it does, what was measured, how you
 * get from nothing to governed, what it does not do, the questions a developer asks
 * before installing anything, and the closing block.
 *
 * Presentational only. No state, no data fetching, so these stay server components and
 * the marketing page keeps rendering without a client bundle.
 *
 * Every figure here is copied from a file in this repository rather than written for
 * the page: README.md for the containment and detection results and the MVP status
 * line, app/benchmark/page.tsx for the AgentDojo denominator and the llm-guard
 * comparison, app/page.tsx and app/how-it-works/page.tsx for the behavioural claims
 * (observe by default, the tool-containment exception, the fail-open contract, the two
 * scanner guarantees). Nothing is rounded, and the numbers that make the product look
 * worse are on the page next to the ones that do not, because leading with those is the
 * reason the rest is believed.
 *
 * Colours come from the --mk-* tokens in app/marketing.css only, so light and dark are
 * both correct without a second set of values here.
 */

/** Duplicated rather than imported: nav.tsx owns its own copy and is edited elsewhere. */
const REPO = "https://github.com/architsharm/agentfox";
const LICENSE = `${REPO}/blob/main/LICENSE`;
const SECURITY = `${REPO}/blob/main/SECURITY.md`;

/** External links all carry the same two attributes; this stops them drifting apart. */
function Out({
  href,
  children,
  className,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
    </a>
  );
}

function SectionHead({
  eyebrow,
  title,
  lede,
}: {
  eyebrow?: string;
  title: string;
  lede?: string;
  center?: boolean;
}) {
  return (
    <div className="mk-narrow mk-up">
      {eyebrow && <span className="mk-eyebrow">{eyebrow}</span>}
      <h2 className="mk-h2" style={{ marginTop: eyebrow ? 14 : 0 }}>
        {title}
      </h2>
      {lede && (
        <p className="mk-lede" style={{ margin: "14px 0 0" }}>
          {lede}
        </p>
      )}
    </div>
  );
}

/* --- 1. Features -------------------------------------------------------- */

const FEATURES: { title: string; body: string; chip?: string }[] = [
  {
    title: "It finds the agents you already have",
    body: "Point it at a repository and it walks the source with a parser to report what talks to a model and which of it is ungoverned. It never imports or runs your code, and onboarding a hosted API reads that API's OpenAPI document without calling a single operation on it.",
  },
  {
    title: "It refuses the call, not the sentence",
    body: "Each agent holds explicit grants for the tools it may call with ceilings on the argument values, each tool carries a declared impact tier, and every argument carries the provenance of where its value came from. A transfer whose recipient came out of a retrieved document is refused or sent to a person because of where the value came from, with no detector involved.",
  },
  {
    title: "The record shows when it has been edited",
    body: "Every decision lands in a tamper-evident audit chain, whether the call was allowed or blocked, next to a trace of the whole path it took. Evidence packages ship with a stdlib-only verifier, so the record does not rest on trusting the process that wrote it.",
  },
  {
    title: "It tests this deployment, not a model in general",
    body: "Adversarial probes fire at your own agents' capability grants and policy bindings in enforce mode, and eval suites can gate CI so a regression fails the build. It tells you whether this deployment got weaker than it was last week, which is configuration regression testing rather than a robustness certificate.",
  },
  {
    title: "Compliance status is computed, not asserted",
    body: "Controls map to the frameworks you answer to, and each control's status comes from telemetry rather than from a claim someone typed into a spreadsheet. The mappings themselves were produced from framework texts by engineers and not reviewed by compliance counsel, so they ship labelled as draft rather than being quietly left out.",
    chip: "Draft mappings",
  },
];

export function Features() {
  return (
    <section id="features" className="mk-section">
      <div className="mk-wrap">
        <SectionHead
          eyebrow="What it does"
          title="Five things, and the last one admits what it is"
          lede="One line in your entry point puts your model SDK calls on this path; tool calls join it through the tool wrapper, the MCP governor, the coding-agent hooks or the gateway. What follows is what each layer is actually for."
          center
        />
        <div className="mk-grid mk-grid-2" style={{ marginTop: 44 }}>
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              className={`mk-card mk-up mk-d${Math.min(i + 1, 5)}`}
              style={{ display: "flex", flexDirection: "column", gap: 10 }}
            >
              <div className="mk-row" style={{ gap: 8 }}>
                <h3 className="mk-h3">{f.title}</h3>
                {f.chip && <span className="mk-chip mk-chip-hold">{f.chip}</span>}
              </div>
              <p className="mk-body" style={{ margin: 0, fontSize: "var(--t-small)" }}>
                {f.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --- 2. Evidence -------------------------------------------------------- */

const STATS: { n: string; label: string; tone?: string }[] = [
  { n: "8 of 8", label: "attacks contained with every detector switched off" },
  { n: "4 of 4", label: "legitimate calls still allowed in that same run" },
  { n: "588 of 588", label: "AgentDojo attack pairs contained, with provenance inferred" },
  { n: "24 of 97", label: "benign AgentDojo tasks ran without escalating to a human", tone: "weak" },
  { n: "26.7%", label: "held-out injection recall of the default detector, our weakest layer", tone: "weak" },
];

export function Evidence() {
  return (
    <section id="evidence" className="mk-section mk-band">
      <div className="mk-wrap">
        <SectionHead
          eyebrow="Evidence"
          title="Measured with every detector switched off"
          lede="Most tools try to recognise the malicious text. We do that too, and we publish how badly it goes: the default detector finds 26.7% of a held-out set (66.7% with the opt-in classifier ensemble), and an attacker who reads the verdict and retries gets 73% of what the default stack does catch through. So we switched every detector off and measured what was left."
          center
        />
        <div className="mk-grid mk-grid-5 mk-up mk-d2" style={{ marginTop: 40 }}>
          {STATS.map((s) => (
            <div key={s.n} className="mk-card mk-stat">
              <b style={{ color: s.tone === "weak" ? "var(--mk-muted)" : "var(--mk-text)" }}>
                {s.n}
              </b>
              <span>{s.label}</span>
            </div>
          ))}
        </div>
        <p
          className="mk-fine mk-up mk-d3"
          style={{ maxWidth: "var(--w-prose)", marginTop: 24 }}
        >
          Session-level taint contains every AgentDojo attack by escalating broadly: three
          benign tasks in four went to a human too. Per-argument taint lets more work run and
          misses 61 attacker calls. The weakest figures are in the set on purpose.
        </p>
        <div
          className="mk-row mk-up mk-d4"
          style={{ justifyContent: "center", marginTop: 22, gap: 10 }}
        >
          <Link href="/benchmark" className="mk-btn mk-btn-outline">
            The numbers, and where a competitor beats us
          </Link>
        </div>
      </div>
    </section>
  );
}

/* --- 3. How it works ---------------------------------------------------- */

const STEPS: { title: string; body: React.ReactNode }[] = [
  {
    title: "Point it at a repository or a live API",
    body: "It proposes what it found: what in your code talks to a model, what is ungoverned, and which tools exist. You register each agent, give it an owner, and correct anything the scan got wrong.",
  },
  {
    title: "Put one line in your entry point, or call it over HTTP",
    body: (
      <>
        One line in the entry point wraps the OpenAI, Anthropic, LiteLLM and LangChain
        clients already running in that process. From any other language, post a single
        tool call, or point an existing client&rsquo;s base URL at the gateway.{" "}
        <Link href="/docs/guides/python-auto">The calls are in the docs.</Link>
      </>
    ),
  },
  {
    title: "Watch in observe mode, where no model traffic is blocked",
    body: "The policy that governs model traffic starts in observe: it records what it would have done and lets the call through. You read what gets flagged against your own traffic and tune the detectors per policy before anything is refused.",
  },
  {
    title: "Turn enforcement on when the findings look right",
    body: (
      <>
        Enforcement is the step that starts blocking model traffic. Until then the
        policy records what it would have done and lets the call through.{" "}
        <Link href="/docs/reference/policies">How to turn it on is in the docs.</Link>
      </>
    ),
  },
];

export function HowItWorks() {
  return (
    <section id="adopt" className="mk-section mk-band">
      <div className="mk-wrap mk-split mk-split-wide">
        <div className="mk-up">

          {/* This heading said "Nothing is blocked until you say so", and then
              "Nothing gets blocked until you say so", and both were contradicted by
              the second paragraph under them. Three shipped packs, two modes.
              src/agentfox/packs/*/policies/: baseline is `mode: observe`,
              eu-ai-act-high-risk is `mode: observe`, tool-containment is
              `mode: enforce`. So an agent is held to its grants from the first
              request and the detector rules watch until you promote them, which is
              what the heading now says rather than what the body has to correct. */}
          <h2 className="mk-h2" style={{ marginTop: 14 }}>
            Detectors watch first. Grants hold from the first request</h2>
          <p className="mk-body" style={{ marginTop: 14 }}>
            The rules that read model traffic ship in observe: they record what they
            would have done and let the call through. You tune against your own traffic,
            then turn them on when the findings look right.
            <br />
            <br />
            One exception is on from day one. A tool that moves money, deletes something
            or sends an email will not accept an argument that came out of a web page, a
            retrieved document or another tool&rsquo;s output. Those calls stop for a
            human.
          </p>
        </div>
        <ol className="mk-steps mk-up mk-d2" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {STEPS.map((s, i) => (
            <li key={s.title} className="mk-step">
              <span className="mk-step-n" aria-hidden="true">
                {i + 1}
              </span>
              <div>
                <h3 className="mk-h3">{s.title}</h3>
                <p className="mk-body" style={{ margin: "6px 0 0", fontSize: "var(--t-small)" }}>
                  {s.body}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* --- 4. Honesty --------------------------------------------------------- */

const LIMITS: { title: string; body: React.ReactNode }[] = [
  {
    title: "Detection is a speed bump, and we measure it against ourselves",
    body: (
      <>
        Held-out injection recall is 26.7% for the default detector and 66.7% with the opt-in
        classifier ensemble. An attacker who reads our verdict and tries again gets 73% of what
        the default stack catches through within 50 attempts.
      </>
    ),
  },
  {
    title: "On detection, a competitor beats us",
    body: (
      <>
        On indirect injection through tool output, an installed{" "}
        <code className="mk-mono">llm-guard</code> is more precise on the same 20 cases: 81.8%
        against our 66.7%. Which is why we lead with containment.
      </>
    ),
  },
  {
    title: "Containment is only as good as the declarations behind it",
    body: (
      <>
        Grants and impact tiers are declared by whoever operates the agent, and every check
        believes them. A tool recorded as read-only that is not read-only is not covered.
      </>
    ),
  },
  {
    title: "It is an early release",
    body: (
      <>
        No SSO. Multi-tenancy is enforced at the session for a single organisation, and this is
        not a managed multi-region offering. Text only: no images, audio or video.
      </>
    ),
  },
];

export function Honesty() {
  return (
    <section id="limits" className="mk-section mk-band">
      <div className="mk-wrap">
        <SectionHead
          eyebrow="What it does not do"
          title="The limits, in our own words, before you find them yourself"
          lede="We do not claim adversarial robustness and we do not believe anyone can claim it honestly today. Here is everything that follows from that."
          center
        />
        <div className="mk-grid mk-grid-4" style={{ marginTop: 40 }}>
          {LIMITS.map((l, i) => (
            <div key={l.title} className={`mk-card mk-up mk-d${Math.min(i + 1, 5)}`}>
              <h3 className="mk-h3">{l.title}</h3>
              <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-small)" }}>
                {l.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --- 5. FAQ ------------------------------------------------------------- */

const QUESTIONS: { q: string; a: React.ReactNode }[] = [
  {
    q: "What does it cost, and under what licence?",
    a: (
      <>
        Apache-2.0, with the full text in <Out href={LICENSE}>LICENSE</Out>. It is free and
        there is nothing to buy: all of the source is in the repository, there is no licence
        key, and nothing is gated behind a paid tier.
      </>
    ),
  },
  {
    q: "Does my traffic or my source leave the machine?",
    a: (
      <>
        No. A repository scan walks your source with a parser, never imports it, never runs it
        and makes no network call. A local install downloads no weights and needs no API key,
        and AgentFox adds no destination of its own.
      </>
    ),
  },
  {
    q: "Where does this sit relative to a gateway or a web application firewall?",
    a: (
      <>
        A firewall reads HTTP. A gateway routes it. Neither knows which agent made the
        call, what it was granted, or where an argument came from. This checks the
        action. It does not replace either of those.
      </>
    ),
  },
  {
    q: "What does it cost in latency?",
    a: (
      <>
        No published figure yet. What is measured: each detector runs under a shipped 40ms
        timeout, and the tool-call check reads no text and calls no model at all.
      </>
    ),
  },
  {
    q: "What happens if the control plane is slow or down?",
    a: (
      <>
        You choose fail open or closed per service. The default is open: the request
        proceeds, and the gap is written down. Tenant isolation, entitlement, data
        access scope, and the audit chain cannot fail open.
      </>
    ),
  },
  {
    q: "What happens on escalate?",
    a: (
      <>
        The tool is not called. The caller gets an approval id instead of a result and the
        request lands on the Approvals screen, the CLI or the API. Every request carries a
        clock, and the default when it runs out is deny.
      </>
    ),
  },
  {
    q: "Does it work outside Python?",
    a: (
      <>
        Yes. Point an existing OpenAI or Anthropic client&rsquo;s base URL at the gateway,
        which speaks the API your code already calls, or post a tool call to the gateway
        and read the verdict back. Neither puts AgentFox code in the application.{" "}
        <Link href="/docs/guides/python-auto">The calls are in the docs.</Link>
      </>
    ),
  },
  {
    q: "How do I try it without installing anything?",
    a: (
      <>
        Open the <Link href="/playground">playground</Link>. There is no account and nothing to
        install, every visitor gets a throwaway sandbox running the same enforcement code the
        product runs in production, and the audit chain on the page reports its own
        verification state as you go. A one-off scan of a directory, from a virtualenv that
        is removed on exit, is in the <Link href="/docs">docs</Link>.
      </>
    ),
  },
];

/**
 * `n` caps how many questions render, because the homepage and the product page
 * want different amounts of this. Eight answers is a support article; four is the
 * set someone actually needs before they will run the install command. The rest
 * stay one click away rather than being deleted.
 */
export function FAQ({ n, more }: { n?: number; more?: boolean } = {}) {
  const shown = n ? QUESTIONS.slice(0, n) : QUESTIONS;
  return (
    <section id="faq" className="mk-section">
      <div className="mk-wrap">
        <SectionHead
          title="Questions"
          center
        />
        <div className="mk-narrow mk-up mk-d2" style={{ marginTop: 32 }}>
          {shown.map((item, i) => (
            <details key={item.q} className="mk-faq" open={i === 0}>
              <summary className="mk-h3">{item.q}</summary>
              <p className="mk-body" style={{ margin: "10px 0 0", fontSize: "var(--t-small)" }}>
                {item.a}
              </p>
            </details>
          ))}
          {more && (
            <p className="mk-fine" style={{ marginTop: 22 }}>
              <Link href="/product#faq">
                {QUESTIONS.length - shown.length} more, on the product page
              </Link>
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

/* --- 6. CTA ------------------------------------------------------------- */

export function CTA() {
  return (
    <section className="mk-section mk-ink-act">
      <div className="mk-wrap">
        <div
          className="mk-card mk-card-raised mk-up"
          style={{ padding: "36px 32px" }}
        >
          <div className="mk-narrow">
            <h2 className="mk-h2">Red team a call in the browser</h2>
            <p className="mk-lede" style={{ marginTop: 12 }}>
              No account. The playground uses the same enforcement code as the product.
            </p>
            <div className="mk-row" style={{ marginTop: 20, gap: 10 }}>
              <Link href="/playground" className="mk-btn mk-btn-primary">
                Open the playground
              </Link>
              <Out href={REPO} className="mk-btn mk-btn-outline">
                Read the source
              </Out>
            </div>
            <p className="mk-fine" style={{ marginTop: 16 }}>
              Offline: no API key, no downloaded weights, no network egress.{" "}
              <Link href="/docs">Install from the docs.</Link>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/* --- 7. Footer ---------------------------------------------------------- */

/**
 * Footer columns. `out` marks a link that leaves the site, which is the only thing
 * that decides between `next/link` and a plain anchor here.
 *
 * The Legal column's four routes are required of a public site rather than chosen:
 * a privacy notice, terms, a security page and the licence and attribution notices.
 * They are linked from every page because a visitor looking for them looks in the
 * footer and nowhere else.
 */
type FootLink = { label: string; href: string; out?: boolean };

/* Derived from lib/nav.ts, like the header, the sitemap and llms.txt. The
   footer is where a reader goes when the header did not have what they
   wanted, so it carries everything the menus carry rather than a curated
   subset that drifts from them. */
const FOOT_PRODUCT: FootLink[] = PRODUCT.sections
  .flatMap((section) => section.items)
  .map((item) => ({ label: item.label, href: item.href }));

const FOOT_RESOURCES: FootLink[] = [
  ...RESOURCES.sections.flatMap((section) => section.items),
  ...FLAT,
].map((item) => ({ label: item.label, href: item.href }));

const FOOT_PROJECT: FootLink[] = [
  { label: "Support", href: "/support" },
  { label: "Source", href: REPO, out: true },
  { label: "Licence: Apache-2.0", href: LICENSE, out: true },
  { label: "Report a vulnerability", href: SECURITY, out: true },
];

const FOOT_LEGAL: FootLink[] = [
  { label: "Privacy", href: "/privacy" },
  { label: "Terms", href: "/terms" },
  { label: "Security", href: "/security" },
  { label: "Legal", href: "/legal" },
];

const FOOT_COLUMNS: [string, FootLink[]][] = [
  ["Product", FOOT_PRODUCT],
  ["Resources", FOOT_RESOURCES],
  ["Project", FOOT_PROJECT],
  ["Legal", FOOT_LEGAL],
];

function FootItem({ label, href, out }: FootLink) {
  return out ? <Out href={href}>{label}</Out> : <Link href={href}>{label}</Link>;
}

export function Footer() {
  return (
    <footer className="mk-footer">
      <div
        className="mk-wrap"
        style={{ display: "flex", flexWrap: "wrap", gap: 28, justifyContent: "space-between" }}
      >
        <div >
          <BrandLockup size={30} sub />
          {/* "Maintained in the open by one developer" and "MVP v0.3" were in the
              footer of all nine pages, so anyone who browsed four of them read that
              this is a v0.3 side project eight times. Both facts are true and both
              stay on the site — on /support and /pricing, once, where a reader is
              asking the question they answer. A footer is not the place to argue
              against yourself. */}
          <p className="mk-fine" style={{ margin: "8px 0 0" }}>
            An open-source control plane for AI agents.
          </p>
        </div>
        <nav
          aria-label="Footer"
          style={{ display: "flex", flexWrap: "wrap", gap: 40, fontSize: "var(--t-small)" }}
        >
          {FOOT_COLUMNS.map(([heading, links]) => (
            <div key={heading} style={{ display: "grid", gap: 8, alignContent: "start" }}>
              <span className="mk-label">{heading}</span>
              {links.map((link) => (
                <FootItem key={link.href} {...link} />
              ))}
            </div>
          ))}
        </nav>
      </div>
      <div className="mk-wrap">
        <p className="mk-fine" style={{ margin: "28px 0 0" }}>
          Apache-2.0. Security reports go through GitHub&rsquo;s private advisories rather than
          a public issue; the route is in SECURITY.md.
        </p>
      </div>
    </footer>
  );
}
