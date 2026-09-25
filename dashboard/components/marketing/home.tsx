import Link from "next/link";
import type { ReactNode } from "react";

import { BoundarySequence } from "@/components/marketing/sequence";
import { EstateScan, TraceAnatomy } from "@/components/marketing/product";
import { Boundary } from "@/components/marketing/boundary";
import { REPO } from "@/components/marketing/nav";

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
          <p className="mk-body" style={{ marginTop: 16, fontSize: "var(--t-body)", maxWidth: "46ch" }}>
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
    <section style={{ position: "relative", overflow: "hidden" }}>
      <div className="mk-wash" aria-hidden />
      <div className="mk-wrap mk-hero" style={{ position: "relative" }}>
        <div>
          {/* Four attempts to get this line right, and what each one got wrong:
                "The injection worked. The transfer didn't." was a riddle — it
              needs you to know what a prompt injection is before the sentence
              parses, and "the transfer" referred to nothing on screen yet.
                "Your agent can only call the tools you gave it" was plain but
              inert: it describes how anyone would assume agents already work,
              so it reads as a restatement rather than a product.
                "Prompt injection stops at the tool call" named the threat, but
              in a practitioner's vocabulary — a CISO reads it cold, a VP Eng
              skims past it.
                This one borrows a category every buyer already understands and
              does the differentiating in one word. "Runtime" is what separates
              it from both neighbours a reader might file it under: a WAF reads
              HTTP at the edge, a text scanner grades a string offline, and this
              sits inline on the call itself. See /compare, which draws the line
              against an actual network firewall — the two pages have to agree,
              so that passage says "not a network firewall, an action-layer one"
              rather than "not a firewall". */}
          {/* A third level above the headline. Mono, because this product's
              subject is code and the panel beside it is a list of tool calls —
              a tracked-out uppercase grotesk here would be the generic choice.
              The dot is a status light: the thing is running. */}
          <p className="mk-kicker mk-up mk-d1">Runtime, on every tool call</p>
          <h1 className="mk-h1 mk-up mk-d2">
            <em>Runtime firewall</em> for AI agents
          </h1>
          {/* Every version of this line before it failed the same way: it described
              the mechanism. "Sits between your agent and its tools, checks each
              call against the permissions you set" is the dictionary definition of
              the word in the headline — a reader who understood "firewall" already
              knew all of it, so the subhead cost them four lines and told them
              nothing.
              A subhead's job is to add what the headline cannot carry. Here that is
              stakes and concreteness: the tools in question move money, delete
              records and send mail, which is why any of this matters, and the
              payoff is that being tricked does not get the model an exception. */}
          <p className="mk-lede mk-up mk-d3" style={{ marginTop: 22, maxWidth: "46ch" }}>
            Your agents read customer data, answer on your behalf, and move money.
            AgentFox checks each of those against what you allowed, and stops the ones
            that fall outside.
          </p>
          {/* The install block used to read `pip install …` / `import agentfox;
              agentfox.auto()` directly beside the stream showing payments.transfer
              refused, which invited exactly one conclusion: add that import and this
              tool call is stopped. It is not. autoguard.py's _PATCHERS are
              (_patch_openai, _patch_anthropic, _patch_litellm, _patch_langchain) —
              model clients — and the only callers of Enforcer.guard_tool_call are
              the LangGraph tool node, the MCP governor, the SDK and the gateway's
              /v1/guard/tool_call. On a security product, implying protection that a
              reader has not actually wired up is the worst error available, so the
              hero no longer pairs an import with a refusal. The two paths are named
              on /how-it-works, and the one action here is the playground. */}
          <div className="mk-row mk-up mk-d4" style={{ marginTop: 30 }}>
            <Link href="/playground" className="mk-btn mk-btn-primary">
              Try it, no account
            </Link>
            <a href={REPO} target="_blank" rel="noreferrer" className="mk-btn mk-btn-outline">
              View the source
            </a>
          </div>
          <p className="mk-fine mk-up mk-d5" style={{ marginTop: 16 }}>
            Runs offline · No API key · Apache-2.0
          </p>
        </div>

        {/* Was a 1600px capture of the findings table. At this width it rendered a
            sidebar, a help paragraph, a filter row and seven columns of 8px grey —
            a picture of a document, with nothing for the eye to land on. */}
        {/* Was a panel of log rows — accurate, and carrying no argument of its
            own. The Boundary draws the thing the product is instead: calls
            approach a check, three cross it, one does not. See boundary.tsx. */}
        <div className="mk-up mk-d3">
          <Boundary />
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
        <p className="mk-label" style={{ marginBottom: 18 }}>
          Works with what you already run
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
    <section id="boundaries" className="mk-section mk-band">
      <div className="mk-wrap">
        <div className="mk-narrow">
          <h2 className="mk-h2 mk-up">Stop the call before it spends, sends or deletes</h2>
          <p className="mk-lede mk-up mk-d1" style={{ marginTop: 16, maxWidth: "58ch" }}>
            One support request, three checks, each against what this agent and the
            person behind it actually hold.
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
export function Around() {
  return (
    <section className="mk-section mk-band">
      <div className="mk-wrap">
        <div className="mk-narrow">
          <h2 className="mk-h2 mk-up">Prove what happened, and find what you missed</h2>
          <p className="mk-lede mk-up mk-d1" style={{ marginTop: 16, maxWidth: "56ch" }}>
            Every governed call leaves a record an auditor can check without us.
          </p>
        </div>

        <div className="mk-split mk-up mk-d2" style={{ marginTop: 36, gap: 28 }}>
          <div>
            <TraceAnatomy />
            <p className="mk-fine" style={{ marginTop: 10 }}>
              One page per request. Tamper-evident, with an independent verifier.
            </p>
          </div>
          <div>
            <EstateScan />
            <p className="mk-fine" style={{ marginTop: 10 }}>
              Reads source without running it. An agent with no owner is a finding.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/* --- 4. Proof ----------------------------------------------------------- */

/**
 * The same run, said in the reader's vocabulary instead of the benchmark's.
 *
 * This section used to be three tiles reading "42 of 42", "552 of 552" and "0
 * detectors switched on". Those are the right numbers and they were the wrong
 * unit: a denominator only means something to someone who already knows what
 * AgentDojo is, and "0 detectors switched on" reads as a missing feature to
 * anyone who does not yet know that is the whole point.
 *
 * So the left column is the attack shape, in the words the reader would use for
 * it, and the number sits beside it as the evidence. Every row is a real
 * scenario from a results file, not a category invented for a marketing grid:
 *
 *   Prompt injection -> tool call   the 42/42 acting-call result,
 *                                   benchmarks/agentdojo_e2e/results
 *   Exfiltration via a tool         containment cb1, capability.denied
 *   Unauthorised transfer           containment cb2/cb3, taint.irreversible_tool
 *                                   and the value constraint
 *   Destructive DELETE              containment cb5, sql.unbounded_mutation
 *                                   and cascade.reaches_destructive
 *
 * The framework line is not decoration either: every identifier on it is a key
 * in src/agentfox/compliance_data/controls.yaml. LLM01 Prompt Injection, LLM02
 * Sensitive Information Disclosure and LLM06 Excessive Agency are the three
 * that map to what this section shows; ATLAS and the Art. 14 rule are named
 * because they are the ones a security reviewer asks about first.
 */
const THREATS: { threat: string; detail: string; result: string; source: string }[] = [
  {
    threat: "Attacker tool calls that act",
    detail: "Write or irreversible calls made on the attacker's behalf",
    result: "42 of 42 contained",
    source: "AgentDojo replay, 617 calls",
  },
  {
    threat: "Exfiltration through an ungranted tool",
    detail: "capability.denied",
    result: "contained",
    source: "containment suite, cb1",
  },
  {
    threat: "Transfer built from attacker-controlled text",
    detail: "taint.irreversible_tool, and the declared value ceiling",
    result: "contained",
    source: "containment suite, cb2 and cb3",
  },
  {
    threat: "Unbounded DELETE in a tool argument",
    detail: "sql.unbounded_mutation, cascade.reaches_destructive",
    result: "contained",
    source: "containment suite, cb5",
  },
];

/* Framework ids, each one a key in compliance_data/controls.yaml. Written out
   rather than abbreviated because a reviewer scans for the exact string. */
const FRAMEWORKS = [
  "OWASP LLM01 Prompt Injection",
  "LLM02 Sensitive Information Disclosure",
  "LLM06 Excessive Agency",
  "MITRE ATLAS",
  "EU AI Act Art. 14",
];

export function Proof() {
  return (
    <section id="proof" className="mk-section">
      <div className="mk-wrap">
        <span className="mk-eyebrow mk-up">Measured with every detector switched off</span>
        <h2 className="mk-h2 mk-up mk-d1" style={{ marginTop: 12, maxWidth: "24ch" }}>
          Detection can fail. Permissions still hold.
        </h2>
        <p className="mk-lede mk-up mk-d2" style={{ marginTop: 16, maxWidth: "56ch" }}>
          617 ground-truth tool calls from AgentDojo, replayed through the same
          tool-call guard with every detector disabled.
        </p>

        <div className="mk-threats mk-up mk-d3">
          {THREATS.map((t) => (
            <div key={t.threat} className="mk-threat">
              <div>
                <b>{t.threat}</b>
                <span className="mk-mono">{t.detail}</span>
                {/* Named per row because these are two different experiments. The
                    42 of 42 is the AgentDojo replay; the three below it are
                    scenarios from the containment suite. Presenting all four under
                    one heading without saying so would let a reader take "42 of 42"
                    as the denominator for every row. */}
                <span className="mk-threat-src">{t.source}</span>
              </div>
              <span className="mk-threat-verdict">{t.result}</span>
            </div>
          ))}

          {/* The denominator sits with the numbers rather than one click away: "42
              of 42" invites "out of what?", and a proof section that makes the
              reader follow a link to find out is doing the opposite of its job. */}
          <div className="mk-threat-foot">
            <p>
              552 of 552 legitimate calls still ran. Three attacker reads got through,
              each one something the agent already held a grant for. The compromised
              agent is the benchmark&rsquo;s premise, not a result of this run.
            </p>
            <div className="mk-row" style={{ gap: 6 }}>
              {FRAMEWORKS.map((f) => (
                <span key={f} className="mk-chip">
                  {f}
                </span>
              ))}
            </div>
          </div>
        </div>

        <p className="mk-row mk-up mk-d5" style={{ marginTop: 24 }}>
          <Link href="/benchmark" className="mk-btn mk-btn-outline">
            See every number
          </Link>
        </p>
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
    <section id="limits" className="mk-section-tight">
      <div className="mk-wrap">
        <div className="mk-honest mk-up">
          <div>
            <h2 className="mk-h3">We publish what this does not do</h2>
            <p className="mk-body">
              Every limit of the benchmark above, and the detection numbers where a
              competing scanner is more precise than ours.
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
