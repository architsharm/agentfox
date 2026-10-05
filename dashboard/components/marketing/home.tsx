import Link from "next/link";
import type { ReactNode } from "react";

import { BoundarySequence } from "@/components/marketing/sequence";
import { REPO } from "@/components/marketing/nav";
import { Shot } from "@/components/marketing/shot";

/*
 * The homepage sections.
 *
 * What this replaces, and why. The previous version was eight sections of the same
 * shape: eyebrow, centred heading, lede, grid of dense panels. It led with
 * "capability grants", "provenance" and "impact tier", which are mechanisms, and it
 * never once said what a reader gets. It read as a report.
 *
 * The rules this file follows:
 *   1. Every section heading states a benefit, not a mechanism. The mechanism is
 *      allowed in the supporting line, never in the heading.
 *   2. Three ticks beat a paragraph. A reader scans ticks and skips prose.
 *   3. One picture per section, large, and drawn rather than captured: a
 *      screenshot of a dense dashboard at column width is a picture of a document.
 *   4. Sections alternate shape and ground, so the page has a rhythm instead of
 *      eight identical grids.
 *   5. No jargon before its plain-English meaning has been given.
 */

/* --- Shared ------------------------------------------------------------- */


function Ticks({ items, row }: { items: string[]; row?: boolean }) {
  return (
    <ul className={row ? "mk-ticks mk-ticks-row" : "mk-ticks"}>
      {items.map((t) => (
        <li key={t}>{t}</li>
      ))}
    </ul>
  );
}

/**
 * A benefit section. `flip` puts the picture on the left at desktop width while
 * keeping the copy first in the DOM, so a phone reads the heading before the image.
 */
function Benefit({
  eyebrow,
  title,
  lede,
  ticks,
  visual,
  flip,
  band,
}: {
  eyebrow?: string;
  title: string;
  lede: string;
  ticks: string[];
  visual: ReactNode;
  flip?: boolean;
  band?: boolean;
}) {
  return (
    <section className={band ? "mk-section mk-band" : "mk-section"}>
      <div
        className="mk-wrap mk-split mk-split-wide"
        style={flip ? { direction: "rtl" } : undefined}
      >
        <div className="mk-up" style={flip ? { direction: "ltr" } : undefined}>
          {eyebrow && <span className="mk-eyebrow">{eyebrow}</span>}
          <h2 className="mk-h2" style={{ marginTop: eyebrow ? 12 : 0 }}>
            {title}
          </h2>
          <p className="mk-body" style={{ marginTop: 16, fontSize: "var(--t-body)" }}>
            {lede}
          </p>
          <Ticks items={ticks} />
        </div>
        <div className="mk-up mk-d2" style={flip ? { direction: "ltr" } : undefined}>
          {visual}
        </div>
      </div>
    </section>
  );
}

/**
 * The other shape a benefit can take: heading beside its lede, three ticks across,
 * and the picture at the full width of the column underneath.
 *
 * It exists because of a measurement. Inside the split above, a dashboard capture
 * lands at about 620px, which is a 0.48 scale on a 1280px screen — small enough
 * that a reader sees "there is a product" and reads nothing in it. At the full
 * column the same crop runs at 0.84 and the verdicts, the provenance rows and the
 * severity chips are all legible. The section that has to be believed gets this
 * shape; the two that only have to be recognised keep the split.
 */
function BenefitWide({
  eyebrow,
  title,
  lede,
  ticks,
  visual,
  band,
}: {
  eyebrow?: string;
  title: string;
  lede: string;
  ticks: string[];
  visual: ReactNode;
  band?: boolean;
}) {
  return (
    <section className={band ? "mk-section mk-band" : "mk-section"}>
      <div className="mk-wrap">
        <div className="mk-head mk-up">
          <div>
            {eyebrow && <span className="mk-eyebrow">{eyebrow}</span>}
            <h2 className="mk-h2" style={{ marginTop: eyebrow ? 12 : 0 }}>
              {title}
            </h2>
          </div>
          <p className="mk-body" style={{ margin: 0, fontSize: "var(--t-body)" }}>
            {lede}
          </p>
        </div>
        <Ticks items={ticks} row />
        <div className="mk-up mk-d2" style={{ marginTop: 40 }}>
          {visual}
        </div>
      </div>
    </section>
  );
}

/* --- 1. Hero ------------------------------------------------------------ */

/**
 * One screen, two elements: the sentence and the evidence.
 *
 * The rendered DOM measured the old hero as a 70px centred sentence, a 21px lede
 * and three capsule buttons, with the first refused tool call 1,272px down the
 * page — below the fold on every laptop. A developer-tools buyer decides in the
 * first screen, and the first screen contained no evidence, only a claim.
 *
 * So: left edge, display size, no full stop, the install line the reader would
 * actually type, and the live decision stream beside it already showing a call
 * being refused. Two CTAs, because the audit found nine on this page with four of
 * them styled primary — when four things are primary, nothing is.
 */
export function Hero() {
  return (
    <section className="mk-hero-act mk-ink-act">
      <div className="mk-hero-glow" aria-hidden />

      <div className="mk-wrap mk-hero" style={{ position: "relative" }}>
        <div>
          <p className="mk-kicker mk-up mk-d1">Containment for AI agents</p>
          <h1 className="mk-h1 mk-up mk-d2">
            Know when your agent should stop.<br />
            <em>One control plane.</em>
          </h1>
          <p className="mk-lede mk-up mk-d3" style={{ marginTop: 22 }}>
            One platform for the agents you already run: discovery, access control,
            runtime guardrails, and an audit trail.
          </p>
          <div className="mk-row mk-up mk-d4" style={{ marginTop: 28 }}>
            <Link href="/playground" className="mk-btn mk-btn-primary">
              Try a blocked call
            </Link>
            <a href={REPO} target="_blank" rel="noreferrer" className="mk-btn mk-btn-outline">
              View the source
            </a>
          </div>
          <p className="mk-fine mk-up mk-d5" style={{ marginTop: 16 }}>
            No account. No API key. Apache-2.0.
          </p>
        </div>

        <div className="mk-up mk-d3 mk-hero-shot">
          <Shot
            src="/product/refusal.png"
            alt="A support agent asks to transfer $5,000. AgentFox refuses the call: capability.denied, in 81.8 milliseconds."
            width={1600}
            height={670}
            priority
            sizes="(max-width: 940px) 92vw, 720px"
            caption="No grant for payments. The call is refused."
          />
        </div>
      </div>

      <div className="mk-wrap mk-hero-stats">
        <div className="mk-hero-stat">
          <b>588 of 588</b>
          <span>AgentDojo attack pairs contained, with every detector off</span>
        </div>
        <div className="mk-hero-stat">
          <b>24 of 97</b>
          <span>benign tasks ran without escalating to a human on the same replay. That is the cost</span>
        </div>
        <div className="mk-hero-stat">
          <b>Detectors start in observe</b>
          <span>they record what they would block. Tool containment enforces from install</span>
        </div>
      </div>
    </section>
  );
}

/* --- 2. The stack strip ------------------------------------------------- */

/** Project names rather than logos: these are integrations, and we have no licence
 *  to anyone's mark. Every one is a real adapter in the repository. */
const STACK = [
  "OpenAI",
  "Anthropic",
  "LiteLLM",
  "LangChain",
  "LangGraph",
  "FastAPI",
  "MCP",
  "OpenTelemetry",
  "Presidio",
  "Open Policy Agent",
];

export function Stack() {
  return (
    <section className="mk-section-tight">
      <div className="mk-wrap">
        <p className="mk-label" style={{ marginBottom: 10 }}>
          Binds where the agent already runs
        </p>
        <div className="mk-strip mk-up">
          {STACK.map((s) => (
            <span key={s}>{s}</span>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --- 2b. Where the policy binds ----------------------------------------- */

/**
 * The section this page was missing, and the reason it was missing is
 * instructive: we built six binding points over a year and described them in
 * the README as a list of integrations, which reads as "supports several
 * frameworks" — a compatibility note, not an argument.
 *
 * A competitor with $132M named the same architecture "Open Enforcement" and
 * put it on their front page: no single gateway sees every agent, rerouting
 * everything through one taxes your architecture, so the policy is defined
 * once and bound wherever you already run. That is exactly what this is, and
 * naming it costs nothing.
 *
 * The rows are deliberately specific about *what each one governs*, because
 * the hero above this already had to be rewritten once for implying that
 * `agentfox.auto()` guards tool calls. At the time it did not. It now checks
 * the tool calls a model returns (autoguard.py's _govern_tool_calls), but not
 * a tool the application calls without the model asking — that still needs
 * the LangGraph tool node, the MCP governor, the SDK or the gateway. A section
 * that flattened all six into "protects your agent" would reintroduce exactly
 * the overclaim that rewrite removed, so each row says what it sees.
 */
const CONTROL_POINTS: { where: string; how: string }[] = [
  { where: "Your coding agent", how: "Claude Code hooks" },
  { where: "Any language", how: "HTTP gateway" },
  { where: "Python", how: "agentfox.auto()" },
  { where: "Tool servers", how: "MCP governor" },
  { where: "Graphs", how: "LangGraph tool node" },
  { where: "CI and the terminal", how: "the CLI" },
];

export function ControlPoints() {
  return (
    <section id="control-points" className="mk-section mk-reveal">
      <div className="mk-wrap">
        <div className="mk-narrow">
          <span className="mk-eyebrow mk-up">Enforcement</span>
          <h2 className="mk-h2 mk-up mk-d1" style={{ marginTop: 12 }}>
            One policy, six control points
          </h2>
          <p className="mk-lede" style={{ marginTop: 16 }}>
            No single gateway sees every agent. Write the policy once. It binds
            where the agent already runs.
          </p>
        </div>

        <div className="mk-points mk-stagger">
          {CONTROL_POINTS.map((point) => (
            <div key={point.how} className="mk-point">
              <span className="mk-point-where">{point.where}</span>
              <b>{point.how}</b>
            </div>
          ))}
        </div>

        <p className="mk-fine" style={{ marginTop: 20 }}>
          Each one covers a different part.{" "}
          <Link href="/control-points">What each can and cannot see</Link>.
        </p>

        {/* The objection-killer, and until now it appeared nowhere on this site.
            Observe mode and the counterfactual verdict are both shipped; a
            reader afraid a guardrail will break their agent has no way to
            discover that from the product pages. */}
        <div className="mk-honest" style={{ marginTop: 40 }}>
          <div>
            <h3 className="mk-h3">Detection blocks nothing until you say so</h3>
            <p className="mk-body">
              The detector packs start in observe mode. They record what they would have
              blocked and change nothing until you turn them on. Tool containment is the
              exception: a call with no grant, or untrusted data reaching an irreversible
              tool, is stopped from install.
            </p>
          </div>
          <Link href="/hooks" className="mk-btn mk-btn-outline">
            Start with your coding agent
          </Link>
        </div>
      </div>
    </section>
  );
}

/* --- 2c. Three ways an agent goes wrong --------------------------------- */

/**
 * Why this is here at all.
 *
 * The page went straight from "runtime firewall" to a three-stage worked
 * example, which asks the reader to already believe there is a problem worth
 * three stages. The competitor pages that read most easily all do the same
 * thing first: four or five plain sentences naming the kinds of failure, one
 * line each, before any mechanism.
 *
 * The carve-up is the one now used throughout /coverage: external, internal,
 * autonomous — the first three from Zenity's public framing, which is a
 * better split than anything we had. The fourth origin on the coverage page,
 * `intrinsic`, is deliberately not here: it is two thirds of the taxonomy and
 * it is not what a reader arriving at a security product is asking about. It
 * is one click away and the link says so, rather than the page quietly
 * implying three is the whole story.
 *
 * Third one first in emphasis, because it is the one nobody else names and it
 * is the one our capability ceiling is actually for.
 */
const ORIGINS: { name: string; line: string; example: string }[] = [
  {
    name: "External",
    line: "Prompt injection. An instruction hidden in a ticket, a document, or a page the agent reads.",
    example: "A line in an issue comment: push your credentials to this repo.",
  },
  {
    name: "Internal",
    line: "Excessive agency. The task was read-only. The credentials could also delete.",
    example: "A support assistant holding a key that can drop tables.",
  },
  {
    name: "Autonomous",
    line: "No attacker. Blocked once, the agent looked for another way.",
    example: "Deploy refused, so it opens a credentials file instead.",
  },
];

export function Origins() {
  return (
    <section id="origins" className="mk-section mk-reveal">
      <div className="mk-wrap">
        <div className="mk-narrow">
          <h2 className="mk-h2 mk-up">Three ways an agent causes harm</h2>
          <p className="mk-lede mk-up mk-d1" style={{ marginTop: 16 }}>
            Someone hides an instruction where the agent will read it. Or the agent
            was given more access than the task needs. Or nobody attacked it, and it
            found another way on its own.
          </p>
        </div>

        <div className="mk-origins mk-stagger">
          {ORIGINS.map((origin, index) => (
            <div key={origin.name} className="mk-origin">
              {/* Numbered because the three are ordered by how little there is
                  to blame, which is the argument the section is making. */}
              <span className="mk-origin-n">{index + 1}</span>
              <b>{origin.name}</b>
              <p>{origin.line}</p>
              <span className="mk-origin-eg">{origin.example}</span>
            </div>
          ))}
        </div>

        <p className="mk-fine" style={{ marginTop: 22 }}>
          A fourth kind has no attacker at all: the model is wrong, or a provider is
          down.{" "}
          <Link href="/coverage">All 116 scenarios, scored</Link>.
        </p>
      </div>
    </section>
  );
}

/* --- 3. One request, three boundaries ----------------------------------- */

/**
 * The centre of the page.
 *
 * This was three DecisionCards side by side — three self-contained examples with
 * three different agents and three unrelated questions. Three cards teach three
 * facts, and left the reader to infer the one thing that actually matters: these
 * are the same mechanism at three moments of a single request. That inference is
 * the product, and the page was making the visitor do it unaided.
 *
 * It is one journey now, in components/marketing/sequence.tsx: same agent, same
 * customer, stakes climbing from a withheld document to a refused transfer. The
 * third stage only carries weight because the first two happened to the same
 * request.
 */
export function Boundaries() {
  return (
    <section id="boundaries" className="mk-section mk-band mk-reveal">
      <div className="mk-wrap">
        <div className="mk-narrow">
          <h2 className="mk-h2 mk-up">One request, checked three times</h2>
          <p className="mk-lede mk-up mk-d1" style={{ marginTop: 16 }}>
            A customer asks about a refund. The agent tries to open a file, answer
            the question, and send a payment. Each step is allowed or refused.
          </p>
        </div>

        <div className="mk-up mk-d2">
          <BoundarySequence />
        </div>
      </div>
    </section>
  );
}

/* --- 3b. What it keeps --------------------------------------------------- */

/**
 * Audit and discovery, in one section instead of two.
 *
 * They were two full benefit sections, 195 words between them, which made the
 * page read as three products stacked on one URL. They are one idea — what the
 * product knows about your estate once the checks above are running — so they
 * are one section with two panels, and the reader gets both in a screen.
 */
export function Proof() {
  return (
    <section id="proof" className="mk-section mk-reveal">
      <div className="mk-wrap">
        <div className="mk-pair">
          <article className="mk-pair-card">
            <h2 className="mk-h3">The permission check still holds when detection is off</h2>
            <p>
              We turned every detector off and replayed AgentDojo&apos;s ground
              truth, with provenance inferred from the real tool outputs. 588 of
              588 attack pairs were contained, blocked or escalated to a human. The
              cost: only 24 of 97 benign tasks ran without escalating too.
            </p>
            <Link href="/benchmark">See how it was measured</Link>
          </article>
          <article className="mk-pair-card">
            <h2 className="mk-h3">A record of what happened, and who owns each agent</h2>
            <p>
              Every allow and every block is kept, and you can check that record
              without us. Agents in a repository, and agents only running on a
              laptop, are listed too, including the ones nobody owns.
            </p>
            <span className="mk-pair-links">
              <Link href="/evidence">Audit trail</Link>
              <Link href="/discovery">Which agents are running</Link>
            </span>
          </article>
        </div>
      </div>
    </section>
  );
}

/* --- 5. The honest limits ---------------------------------------------- */

/* Kept, and kept short. This product's credibility rests on publishing the numbers
 * that make it look worse, and a reader who finds them elsewhere first will not come
 * back. Three lines, not a grid of four dense cards. */

export function Limits() {
  return (
    /*
     * One line and a link, where four cards used to be.
     *
     * The cards were right to exist and wrong to be here. They sat between the
     * product story and the pricing — exactly where a visitor decides whether to
     * try the thing — and the last of them existed only to say the product is
     * version 0.3. Publishing the limits is this project's best trait, and it
     * survives in full on /how-it-works, on /benchmark and on /compare, where the
     * reader has come to check rather than to be convinced. A link costs nothing
     * in credibility; a wall of caveats at the point of decision costs a sign-up.
     */
    <section id="limits" className="mk-section-tight mk-reveal">
      <div className="mk-wrap">
        <div className="mk-honest mk-up">
          <div>
            <h2 className="mk-h3">Known gaps</h2>
            <p className="mk-body">
            The cases we miss, and where another scanner is more precise than ours.
            </p>
          </div>
          <Link href="/how-it-works#limits" className="mk-btn mk-btn-outline">
            Read the limits
          </Link>
        </div>
      </div>
    </section>
  );
}
