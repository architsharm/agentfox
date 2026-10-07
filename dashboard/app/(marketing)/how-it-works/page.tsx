import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";
import { MarketingNav } from "@/components/marketing/nav";
import { CTA, Footer } from "@/components/marketing/sections";
import { RequestPath } from "@/components/marketing/path";
import { Pane, TraceAnatomy } from "@/components/marketing/product";
import { FollowRequest } from "@/components/marketing/follow";

export const metadata: Metadata = publicPageMetadata({
  title: "What happens when an agent calls a tool",
  description:
    "The prompt, the documents it read, whether the call was allowed, and the record left behind.",
  path: "/how-it-works",
});

const CONNECTS = [
  {
    where: "Python",
    what: "One line in the entry point. It sees prompts, replies, and the tool calls the model asks for. It does not see tools your code calls on its own.",
  },
  {
    where: "Any language",
    what: "Point an OpenAI or Anthropic client at the gateway. Same checks, and no AgentFox code in the application.",
  },
  {
    where: "The tool call",
    what: "LangGraph, the MCP governor, or the SDK. The grant, the argument limits, and where each value came from.",
  },
  {
    where: "Retrieval",
    what: "From your own retrieval code. Documents this person is not allowed to see never reach the prompt.",
  },
] as const;

export default function HowItWorks() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <h1 className="mk-h1">What happens on a tool call</h1>
            <p className="mk-lede" style={{ marginTop: 18 }}>
              The prompt, the documents it read, whether the call was allowed, and the
              record left behind.
            </p>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <h2 className="mk-h2">Where you connect it</h2>
            <p className="mk-lede" style={{ marginTop: 14 }}>
              Four places. Connecting one does not cover the others.{" "}
              <Link href="/docs/guides/python-auto">The calls are in the docs.</Link>
            </p>
            <div className="mk-grid mk-grid-pair" style={{ marginTop: 28 }}>
              {CONNECTS.map((c) => (
                <div key={c.where} className="mk-card">
                  <h3 className="mk-h3">{c.where}</h3>
                  <p className="mk-body" style={{ margin: "8px 0 0" }}>
                    {c.what}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <h2 className="mk-h2">The path, when all four are connected</h2>
            <p className="mk-lede" style={{ marginTop: 14 }}>
              Three of these can end the call before it goes any further.
            </p>
            <div style={{ marginTop: 28 }}>
              <FollowRequest
                frames={[
                  {
                    at: 0,
                    label: "who is behind this call",
                    body: (
                      <Pane label="agentfox · identity" status="governed">
                        <div className="fr-rows">
                          <div>
                            <span className="mk-label">agent</span>
                            <code className="mk-mono">support-triage</code>
                          </div>
                          <div>
                            <span className="mk-label">acting for</span>
                            <code className="mk-mono">alex@example.com</code>
                          </div>
                          <div>
                            <span className="mk-label">quarantined</span>
                            <code className="mk-mono">no</code>
                          </div>
                        </div>
                      </Pane>
                    ),
                  },
                  {
                    at: 2,
                    label: "what retrieval returned",
                    body: (
                      <Pane label="agentfox · retrieval" status="filtered">
                        <ul className="seq-rows">
                          <li className="seq-row seq-row-kept">
                            <span className="mk-mono">billing/refund-policy</span>
                            <i>returned</i>
                          </li>
                          <li className="seq-row seq-row-kept">
                            <span className="mk-mono">orders/ord_88213</span>
                            <i>returned</i>
                          </li>
                          <li className="seq-row seq-row-cut">
                            <span className="mk-mono">hr/salaries-2026</span>
                            <i>withheld</i>
                          </li>
                        </ul>
                      </Pane>
                    ),
                  },
                  {
                    at: 5,
                    label: "the action, checked before it runs",
                    body: (
                      <Pane label="agentfox · tool call" status="blocked">
                        <ul className="seq-rows">
                          <li className="seq-row seq-row-blocked">
                            <span className="mk-mono">payments.transfer</span>
                            <i>block</i>
                          </li>
                          <li className="seq-row seq-row-quiet">
                            <span className="mk-mono">amount: 5000 to: acct_x</span>
                          </li>
                          <li className="seq-row seq-row-quiet">
                            <span>the amount came from a tool result</span>
                          </li>
                        </ul>
                        <p className="fr-rule">
                          <code className="mk-mono">capability.denied</code>
                        </p>
                      </Pane>
                    ),
                  },
                  {
                    at: 7,
                    label: "the record it produces",
                    body: <TraceAnatomy />,
                  },
                ]}
              >
                <RequestPath
                  stations={[
                    {
                      title: "A call arrives",
                      body: "Which agent, and who it is acting for. A quarantined agent stops here.",
                      stops: true,
                    },
                    {
                      title: "Is this something it should answer?",
                      body: "A question outside what you said the agent knows is refused. No model call.",
                      stops: true,
                    },
                    {
                      title: "Retrieval is filtered",
                      body: "Documents this person may not see never reach the prompt.",
                    },
                    {
                      title: "Each piece of text keeps its source",
                      body: "Typed, retrieved, from a tool, from another agent, or from memory.",
                    },
                    {
                      title: "Detectors read the text",
                      body: "Each under a time budget. This is the layer we trust least.",
                    },
                    {
                      title: "Before the tool runs, the action is checked",
                      body: "Grant, argument limits, and where the values came from. This check does not read the text.",
                      stops: true,
                      keystone: true,
                    },
                    {
                      title: "The reply is checked too",
                      body: "Including things like personal data, and the answer is tied to its sources.",
                    },
                    {
                      title: "It lands in a record",
                      body: "Allowed or blocked, in a chain you can verify without our code.",
                    },
                  ]}
                />
              </FollowRequest>
            </div>
            <p className="mk-fine" style={{ marginTop: 22 }}>
              The first five steps are what most products in this space do. The sixth is
              the one that still holds when detection misses.{" "}
              <Link href="/benchmark">The measurements are here.</Link>
            </p>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <h2 className="mk-h2">What this does not do</h2>
            <div className="mk-grid mk-grid-pair" style={{ marginTop: 28 }}>
              <div className="mk-card">
                <h3 className="mk-h3">It does not make an agent attack-proof</h3>
                <p className="mk-body" style={{ margin: "8px 0 0" }}>
                  An attacker who can read the verdict and retry gets through. We measure
                  that, and we publish it.
                </p>
              </div>
              <div className="mk-card">
                <h3 className="mk-h3">It believes what you declare</h3>
                <p className="mk-body" style={{ margin: "8px 0 0" }}>
                  A destructive tool recorded as read-only is treated as read-only. The
                  check cannot see past that.
                </p>
              </div>
              <div className="mk-card">
                <h3 className="mk-h3">It does not change your other systems</h3>
                <p className="mk-body" style={{ margin: "8px 0 0" }}>
                  It bounds what an agent does with access you already gave it. It does
                  not grant or revoke that access.
                </p>
              </div>
              <div className="mk-card">
                <h3 className="mk-h3">Model traffic starts in observe</h3>
                <p className="mk-body" style={{ margin: "8px 0 0" }}>
                  It records what it would have blocked, and lets the call through, until
                  you turn enforcement on. Tool containment is the exception: that one
                  blocks from the start.
                </p>
              </div>
            </div>
          </div>
        </section>
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
