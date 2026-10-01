"use client";

import Link from "next/link";
import { useState } from "react";

/**
 * The platform section — the thing this site did not have.
 *
 * The diagnosis that produced it: we were presenting a toolkit and the
 * competitors are presenting a platform. They name four or five products and
 * put a verb in front of each — "Discover with AI-SPM", "Protect with AI-DR"
 * — so a buyer reads the section once and knows what they would be buying.
 * We shipped every one of those capabilities and named none of them; the nav
 * said "discovery", "grants", "runtime guardrails", which are descriptions of
 * features, not products.
 *
 * The category names below are industry terms, not a competitor's brands.
 * AI-SPM and AI-DR are what this market calls posture management and runtime
 * detection, and a buyer searches for them by those names. Using the
 * vocabulary a reader already has is the opposite of cargo-culting: inventing
 * "AgentFox Sentinel" would be the cargo cult.
 *
 * Every bullet is a fact from the product, and the link goes to the page that
 * carries it in depth. A platform section whose claims do not resolve to
 * anything is the exact failure this project spends its credibility avoiding.
 */

type Pillar = {
  verb: string;
  product: string;
  headline: string;
  points: string[];
  href: string;
  cta: string;
};

const PILLARS: Pillar[] = [
  {
    verb: "Discover",
    product: "AI-SPM",
    headline: "Find every agent, tool, MCP server and skill",
    points: [
      "Scans your repository without running it",
      "Picks up agents running locally, not just committed code",
      "Snapshots MCP tools so later changes are caught",
      "Flags any agent with no owner",
    ],
    href: "/discovery",
    cta: "How discovery works",
  },
  {
    verb: "Govern",
    product: "Access control",
    headline: "Set what each agent is allowed to do",
    points: [
      "Every tool is read, write, high impact or irreversible",
      "Grants carry limits: a value ceiling, an environment, a data source",
      "Data from a document can fill a value but cannot choose an action",
      "Anything you have not granted is refused",
    ],
    href: "/grants",
    cta: "How access control works",
  },
  {
    verb: "Protect",
    product: "Runtime",
    headline: "The tool call is checked before it runs",
    points: [
      "Prompts, tool calls, results, documents, and completions",
      "50 rules in four packs, as YAML in the repo",
      "A detector that runs out of time is marked, not skipped",
      "Starts in observe mode and changes nothing until you turn it on",
    ],
    href: "/runtime",
    cta: "How runtime guardrails work",
  },
  {
    verb: "Test",
    product: "Red team",
    headline: "Red team this deployment",
    points: [
      "116 failure scenarios",
      "105 of them run against the product every night",
      "42 of 42 attacker tool calls blocked with all detectors off",
      "We publish the ones we miss too",
    ],
    href: "/coverage",
    cta: "See the red team coverage",
  },
  {
    verb: "Prove",
    product: "Audit",
    headline: "An audit trail an auditor can verify",
    points: [
      "A verifier an auditor can run without our code",
      "Each record links to the one before it, so a deletion shows up",
      "43 controls across seven frameworks, including the EU AI Act",
      "Status comes from telemetry, not a questionnaire",
    ],
    href: "/evidence",
    cta: "How the audit trail works",
  },
];

export function Platform() {
  const [active, setActive] = useState(0);
  const p = PILLARS[active];

  return (
    <section id="platform" className="mk-section mk-ink-act mk-reveal">
      <div className="mk-wrap">
        <div className="mk-narrow">
          <p className="mk-kicker">The platform</p>
          <h2 className="mk-h2" style={{ marginTop: 14 }}>
            Discover, govern, protect, test, prove.
          </h2>
          <p className="mk-lede" style={{ marginTop: 16 }}>
            One platform for discovery, access control, runtime guardrails, red teaming, and an audit trail.
          </p>
        </div>

        {/* A tablist, properly: arrow keys move between tabs and the panel is
            labelled by the tab that opened it. A row of divs with onClick is
            the usual version of this and it is unusable without a mouse. */}
        <div className="pf" style={{ marginTop: 40 }}>
          <div className="pf-tabs" role="tablist" aria-label="What the platform does">
            {PILLARS.map((pillar, i) => (
              <button
                key={pillar.product}
                role="tab"
                id={`pf-tab-${i}`}
                aria-selected={i === active}
                aria-controls={`pf-panel-${i}`}
                tabIndex={i === active ? 0 : -1}
                className={i === active ? "pf-tab pf-tab-on" : "pf-tab"}
                onClick={() => setActive(i)}
                onKeyDown={(e) => {
                  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
                  e.preventDefault();
                  const next =
                    e.key === "ArrowRight"
                      ? (i + 1) % PILLARS.length
                      : (i - 1 + PILLARS.length) % PILLARS.length;
                  setActive(next);
                  document.getElementById(`pf-tab-${next}`)?.focus();
                }}
              >
                <span className="pf-verb">{pillar.verb}</span>
                <span className="pf-product">{pillar.product}</span>
              </button>
            ))}
          </div>

          <div
            className="pf-panel"
            role="tabpanel"
            id={`pf-panel-${active}`}
            aria-labelledby={`pf-tab-${active}`}
            /* Keyed so the panel re-mounts on change and the entrance runs.
               Without it React reuses the node and the switch is a jump. */
            key={active}
          >
            <h3>{p.headline}</h3>
            <ul>
              {p.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
            <Link href={p.href} className="mk-btn mk-btn-outline">
              {p.cta}
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
