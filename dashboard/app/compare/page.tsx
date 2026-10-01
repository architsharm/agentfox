import type { CSSProperties } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { publicPageMetadata } from "@/lib/site";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";

export const dynamic = "force-dynamic";

/**
 * The competitive page, written to survive a reader who already sells one of these.
 *
 * Two rules govern every line below, and they are the reason the page is worth
 * publishing at all:
 *
 *  1. No claim about a competitor appears here unless it is in
 *     `docs/competitor-analysis.md` (dated 2026-09-04), in README.md's "Where this
 *     sits in the market" section, or measured in `benchmarks/`. The source is named
 *     in the copy, not just in this comment, so a reader can check it.
 *  2. No ticks and crosses against a named company. We cannot verify what any vendor
 *     ships from their marketing pages. The table compares categories. One vendor is
 *     named, `llm-guard`, because `benchmarks/agent_security/` scores it from a real,
 *     separately installed copy through an actual `PromptInjection().scan()` call.
 *
 * The concessions come before the differences on purpose. Every figure in the
 * concessions section is either a measurement of ours that is worse than someone
 * else's, or a capability we do not have. `docs/competitor-analysis.md` Â§5 is the
 * source for most of them and says the same thing in the same order.
 */

export const metadata: Metadata = publicPageMetadata({
  title: "AI governance and runtime security",
  description:
    "Governance platforms and runtime tools, where each camp beats us, including a measured loss to llm-guard, and what least privilege changes when detection fails.",
  path: "/compare",
});

const ANALYSIS = "https://github.com/architsharm/agentfox/blob/main/docs/competitor-analysis.md";
const TIER_README =
  "https://github.com/architsharm/agentfox/blob/main/benchmarks/agent_security/README.md";

function Out({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

/* --- Table furniture ---------------------------------------------------- */

/* A wide table cannot reflow into 375px without becoming unreadable, so it keeps a
   minimum width and its own horizontal scroller. Nothing else on the page scrolls. */
const SCROLLER: CSSProperties = { padding: 0, overflowX: "auto" };
const TABLE: CSSProperties = {
  width: "100%",
  minWidth: 720,
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

/* --- 1. The two camps --------------------------------------------------- */

const CAMPS: { title: string; chip: string; owns: string; lacks: string; who: string }[] = [
  {
    title: "GRC governance platforms",
    chip: "Credo AI, OneTrust, ModelOp",
    owns: "Policy, the model registry, framework mapping, and the relationships a buyer already has with an auditor.",
    lacks:
      "Built for the model era. README records no runtime enforcement, no execution paths and no evaluation; the competitor analysis notes this is eroding rather than absolute, with runtime paths appearing across the camp.",
    who: "The camp a CISO or a compliance lead has usually already bought.",
  },
  {
    title: "Agent-security tools",
    chip: "Arthur, Zenity, Lakera, Prisma AIRS, Agent 365",
    owns: "Runtime guardrails, some of them with real depth: sandboxing, adaptive red teaming, network capture.",
    lacks:
      "Thin on compliance framework mapping, and several are locked to one vendor’s model, cloud or security suite.",
    who: "The camp a platform or security engineer reaches for first.",
  },
];

/* --- 2. Where competitors win ------------------------------------------- */

const LOSSES: { title: string; body: React.ReactNode; source: string }[] = [
  {
    title: "llm-guard is more precise than we are",
    body: (
      <>
        On indirect injection through tool output, across the same 20 cases, an installed{" "}
        <code className="mk-mono">llm-guard</code> scores 81.8% precision against our 66.7%. It
        raised 2 false positives on the benign half where we raised 5.
      </>
    ),
    source: "benchmarks/agent_security/README.md, Tier B",
  },
  {
    title: "Detection quality is not where we lead",
    body: (
      <>
        Cleanlab, Vectara, Galileo and Patronus all do model-based groundedness scoring, and
        our own competitor analysis records them as benchmarked ahead of our lexical scorer.
      </>
    ),
    source: "docs/competitor-analysis.md, sections 4.3 and 5",
  },
  {
    title: "A model provider bundles this with the runtime",
    body: (
      <>
        Identity, permissions, audit and evaluations arrive bundled with the runtime itself from
        OpenAI, Microsoft, Anthropic and Google. The analysis assumes Microsoft Entra Agent ID
        simply wins agent identity, and that the plumbing layer gets commoditised.
      </>
    ),
    source: "docs/competitor-analysis.md, sections 2 and 8",
  },
  {
    title: "A GRC incumbent has the auditor relationships",
    body: (
      <>
        Credo AI ships purpose-built policy packs and CE-marking support for EU AI Act filings.
        All 300 of our framework mappings remain DRAFT, produced from framework texts by
        engineers and unreviewed by compliance counsel.
      </>
    ),
    source: "docs/competitor-analysis.md, section 5",
  },
  {
    title: "OneTrust and IBM have what procurement asks for",
    body: (
      <>
        OneTrust has a roughly 14,000-organisation installed base and third-party AI vendor risk
        workflows. IBM watsonx.governance has AI Factsheets, SR 11-7 model-risk workflows and
        FedRAMP GovCloud. We have none of that.
      </>
    ),
    source: "docs/competitor-analysis.md, section 5",
  },
  {
    title: "Three capabilities we simply do not have",
    body: (
      <>
        ServiceNow AI Control Tower has around 30 discovery integrations; our discovery is
        repository and config based. Kosmoy has kernel-enforced sandboxing; we do not sandbox at
        all. Zenity prevents inline inside Copilot Studio; we have zero coverage of that surface.
      </>
    ),
    source: "docs/competitor-analysis.md, section 5",
  },
];

/* --- 3. Category table -------------------------------------------------- */

const ROWS: [string, string, string, string][] = [
  [
    "Policy, registry, framework mapping",
    "Owns it",
    "Thin on it",
    "300 framework mappings, all DRAFT",
  ],
  [
    "Runtime enforcement on model traffic",
    "Thin to absent, and eroding",
    "Owns it",
    "Yes, observe mode by default",
  ],
  [
    "Containment after a detector misses",
    "Not claimed",
    "Detection-led language",
    "8 of 8 with every detector off",
  ],
  [
    "Blast-radius analysis of generated SQL",
    "None surveyed",
    "None surveyed",
    "Statement level, real parser",
  ],
  [
    "Failure attribution across a handoff",
    "None surveyed",
    "None surveyed",
    "Names the step that introduced the value",
  ],
  ["Sandboxed execution", "No", "Some of the camp", "No, and out of scope"],
  ["Estate-scale discovery connectors", "Yes, breadth varies", "Yes, breadth varies", "Repository and config only"],
  ["Low-code and Copilot agent surface", "Partly", "Covered", "Not covered, a stated non-goal"],
  ["Self-host with zero egress", "Several are SaaS only", "Several are SaaS only", "The default"],
  ["Licence", "Commercial", "Commercial", "Apache-2.0, nothing gated"],
  ["Marketplace listing and SOC 2 Type II", "Almost all have one", "Almost all have one", "Neither; 6 of 14 procurement bars met"],
];

/* --- 4. What is different ----------------------------------------------- */

const DIFFERENT: { title: string; body: string }[] = [
  {
    title: "Containment does not wait for a detector",
    body: "A value out of a retrieved document is structurally blocked from an irreversible tool, whether or not any detector fired. Measured with the detectors switched off entirely, which is a total bypass rather than a simulated miss.",
  },
  {
    title: "Vendor neutral by construction",
    body: "It governs OpenAI, Anthropic, LiteLLM and LangChain traffic in the same process, and has no model, cloud or security suite of its own to sell you. A model provider cannot make that claim about its own runtime.",
  },
  {
    title: "Self-hosted, with nothing leaving",
    body: "A local install downloads no weights, needs no API key and adds no destination of its own. The competitor analysis records Zenity, Credo AI and OneTrust as SaaS only.",
  },
  {
    title: "Apache-2.0, including the part that decides",
    body: "The enforcement path, the policy engine and the audit verifier are all readable. Nothing is behind a licence key or a paid tier.",
  },
];

export default function Compare() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <h1 className="mk-h1 mk-up mk-d1">
              Governance platforms and <em>runtime tools</em></h1>
            <p className="mk-lede mk-up mk-d2" style={{ marginTop: 20 }}>
              Where a governance platform is ahead of us, and where a runtime tool is.
            </p>
            <p className="mk-fine mk-up mk-d3" style={{ marginTop: 18 }}>
              Every competitor statement below comes from{" "}
              <Out href={ANALYSIS}>docs/competitor-analysis.md</Out> or a benchmark in this
              repository, named next to the claim. No vendor is scored from its own marketing
              pages.
            </p>
          </div>
        </section>

        {/* 1. The camps */}
        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="The landscape"
              title="What each camp genuinely owns"
              lede="Governance platforms own the policy. Runtime tools own the call. These are the descriptions we can check."
            />
            <div className="mk-grid mk-grid-2" style={{ marginTop: 40 }}>
              {CAMPS.map((c, i) => (
                <div
                  key={c.title}
                  className={`mk-card mk-up mk-d${i + 1}`}
                  style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}
                >
                  <div className="mk-row" style={{ gap: 8 }}>
                    <h3 className="mk-h3">{c.title}</h3>
                  </div>
                  <span className="mk-chip">{c.chip}</span>
                  <div>
                    <span className="mk-label">Good at</span>
                    <p className="mk-body" style={{ margin: "5px 0 0", fontSize: "var(--t-small)" }}>
                      {c.owns}
                    </p>
                  </div>
                  <div>
                    <span className="mk-label">Thin on</span>
                    <p className="mk-body" style={{ margin: "5px 0 0", fontSize: "var(--t-small)" }}>
                      {c.lacks}
                    </p>
                  </div>
                  <p className="mk-fine" style={{ margin: 0 }}>
                    {c.who}
                  </p>
                </div>
              ))}
            </div>
            <p
              className="mk-fine mk-up mk-d3"
              style={{ maxWidth: "var(--w-prose)", marginTop: 24 }}
            >
              The alternative that wins most often is neither camp: 6 of 11 vetted senior
              engineers had already hand-built a guardrail layer inside their employer. The
              analysis calls that competing with <code className="mk-mono">git init</code>.
            </p>
          </div>
        </section>

        {/* 2. Where they win */}
        <section className="mk-section mk-band mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="Concessions"
              title="Where a competitor beats us"
              lede="With the number and the document each one came from."
            />
            <div className="mk-grid mk-grid-2" style={{ marginTop: 40 }}>
              {LOSSES.map((l, i) => (
                <div
                  key={l.title}
                  className={`mk-card mk-up mk-d${Math.min(i + 1, 5)}`}
                  style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}
                >
                  <h3 className="mk-h3">{l.title}</h3>
                  <p className="mk-body" style={{ margin: 0, fontSize: "var(--t-small)" }}>
                    {l.body}
                  </p>
                  <code
                    className="mk-mono"
                    style={{ color: "var(--mk-muted)", overflowWrap: "anywhere", marginTop: "auto" }}
                  >
                    {l.source}
                  </code>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* 3. The measured head-to-head */}
        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="The one measured comparison"
              title="Against a real llm-guard install"
              lede="The only vendor we installed and scored ourselves."
            />
            <div className="mk-narrow" style={{ marginTop: 36 }}>
              <p className="mk-fine mk-up" style={{ margin: "0 0 12px" }}>
                Indirect injection through tool output, 20 identical strings: 10 real shapes and
                10 benign documents using the same vocabulary.
              </p>
              <div className="mk-card mk-up" style={SCROLLER}>
                <table style={TABLE}>
                  <thead>
                    <tr>
                      <th style={TH}></th>
                      <th style={TH}>Precision</th>
                      <th style={TH}>Recall</th>
                      <th style={TH}>False positives</th>
                      <th style={TH}>False negatives</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td style={TD_HEAD}>AgentFox, full detector stack</td>
                      <td style={TD}>66.7%</td>
                      <td style={TD_HEAD}>100.0%</td>
                      <td style={TD}>5</td>
                      <td style={TD}>0</td>
                    </tr>
                    <tr>
                      <td style={TD_HEAD}>
                        llm-guard, <code className="mk-mono">PromptInjection</code>
                      </td>
                      <td style={TD_HEAD}>81.8%</td>
                      <td style={TD}>90.0%</td>
                      <td style={TD}>2</td>
                      <td style={TD}>1</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mk-fine mk-up mk-d2" style={{ marginTop: 16 }}>
                Source: <Out href={TIER_README}>benchmarks/agent_security/README.md</Out>, Tier B.
                Every llm-guard figure came from a real{" "}
                <code className="mk-mono">PromptInjection().scan()</code> call in a separate
                interpreter, not an asserted number.
              </p>
              <p className="mk-body mk-up mk-d3" style={{ marginTop: 14, fontSize: "var(--t-small)" }}>
                llm-guard wins precision here by 15.1 points, and that cost is ours to carry. The
                other three tiers in that suite are reported as outside its design rather than
                scored as a loss for it, because a stateless text scanner has no tool registry, no
                capability model and no way to see a structured argument.
              </p>
            </div>
          </div>
        </section>

        {/* 4. Category table */}
        <section className="mk-section mk-band mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="Category by category"
              title="Capabilities, by camp rather than by vendor"
              lede="Columns are categories. Ticks against a named company would mean trusting that company’s marketing page, which we cannot check."
            />
            <div className="mk-card mk-up mk-d2" style={{ ...SCROLLER, marginTop: 36 }}>
              <table style={TABLE}>
                <thead>
                  <tr>
                    <th style={TH}>Capability</th>
                    <th style={TH}>GRC governance platforms</th>
                    <th style={TH}>Agent-security tools</th>
                    <th style={TH}>AgentFox</th>
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map(([cap, grc, sec, us]) => (
                    <tr key={cap}>
                      <td style={TD_HEAD}>{cap}</td>
                      <td style={TD}>{grc}</td>
                      <td style={TD}>{sec}</td>
                      <td style={TD}>{us}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mk-fine mk-up mk-d3" style={{ marginTop: 16 }}>
              &ldquo;None surveyed&rdquo; is the competitor analysis speaking about the field it
              checked, not a claim that nobody anywhere does this. The 8 of 8 figure is the
              containment benchmark with every detector switched off. The procurement row counts
              the 14 standard enterprise requirements that document tracks, of which 8 are still
              open, including SOC 2 Type II, ISO 27001 and an uptime SLA.
            </p>
          </div>
        </section>

        {/* 5. Different */}
        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="The difference"
              title="What is actually different here"
              lede="Four things, each checkable in the repository."
            />
            <div className="mk-grid mk-grid-4" style={{ marginTop: 40 }}>
              {DIFFERENT.map((d, i) => (
                <div key={d.title} className={`mk-card mk-up mk-d${Math.min(i + 1, 5)}`}>
                  <h3 className="mk-h3">{d.title}</h3>
                  <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-small)" }}>
                    {d.body}
                  </p>
                </div>
              ))}
            </div>
            <p
              className="mk-lede mk-up mk-d5"
              style={{ marginTop: 40 }}
            >
              The numbers are on <Link href="/benchmark">the benchmark page</Link>, the mechanism
              on <Link href="/product">the product page</Link>.
            </p>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
