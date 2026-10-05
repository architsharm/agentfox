import type { Metadata } from "next";
import { publicPageMetadata } from "@/lib/site";
import Link from "next/link";
import { REPO } from "./_public";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { RequestPath } from "@/components/marketing/path";
import { Pane, TraceAnatomy } from "@/components/marketing/product";
import { FollowRequest } from "@/components/marketing/follow";

/**
 * Public explainer for someone who has never seen this product, reached from the
 * landing page at "/" and from the public header on every signed-out page.
 *
 * Public because it is useless if it is behind the sign-in wall: it exists for the
 * reader who arrived at the root URL from a link and does not yet know what any of
 * this is. See middleware.ts (PUBLIC_PATHS) and layout.tsx (isChromelessPage).
 *
 * The request path below is the sequence in docs/hld.md §6, which is itself
 * verified against enforcement.py's preflight/evaluate/call_provider and the
 * gateway's chat_completions handler. It is compressed into plain language and
 * loses some ordering detail (budget caps, circuit breaker, attribution graph) on
 * purpose; it does not add anything that is not in that sequence. The six areas
 * are the six pillars in README.md. Numbers appear only where README.md or
 * app/benchmark/page.tsx already publishes them, and everything else links to
 * /benchmark rather than restating a figure.
 */

export const metadata: Metadata = publicPageMetadata({
  title: "What happens when an agent calls a tool",
  description:
    "The prompt, the documents it read, whether the call was allowed, and the record left behind.",
  path: "/how-it-works",
});

export default function HowItWorks() {
  return (
    /* The site's own nav and footer, and the hero the other public pages open with.
       This page kept a header of its own from before there was a marketing layer,
       which meant the one page explaining the product was also the one page that did
       not look like the product's site. The article underneath is unchanged. */
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
              <h1 className="mk-h1">
                What happens when an agent calls a tool</h1>
              <p className="mk-lede" style={{ marginTop: 18 }}>
                The prompt, the documents it read, whether the call was allowed, and the record left behind.
              </p>
          </div>
        </section>

      <section className="mk-section">
      <div className="mk-wrap">
        <article className="bm-doc">

        <h2>The path one call takes</h2>
        {/* This said "three ways on … the sequence is the same for all three",
            which is not true and is the kind of untrue that costs a reader real
            protection. autoguard.py's _PATCHERS are the OpenAI, Anthropic,
            LiteLLM and LangChain clients, so `auto()` governs model traffic, the
            answerability gate in front of it, and the tool calls that come back
            in a response — not a tool your code calls without the model asking,
            and not retrieval, which is filtered where your own code asks for it.
            A visitor could otherwise add one import and believe every tool was
            governed. */}
        <h3>Where it connects, and what each connection can check</h3>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Connect it here</th>
                <th>And it checks</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>One line in a Python entry point</td>
                <td>
                  Model traffic: detectors over prompts and responses, the answerability
                  gate before the call, the kill switch and budgets. Plus the tool calls
                  the model asks for, before your code runs them.{" "}
                  <strong>Not tools your code calls on its own.</strong>
                </td>
              </tr>
              <tr>
                <td>The gateway. Point an OpenAI or Anthropic client&apos;s base URL at it</td>
                <td>
                  The same model-traffic checks, from any language, with no AgentFox code
                  in your application
                </td>
              </tr>
              <tr>
                <td>
                  A governed tool path: the LangGraph node, the MCP governor, or the SDK
                </td>
                <td>
                  The action itself: the agent&apos;s grants, declared argument ceilings,
                  where each value came from, and whether the tool is irreversible
                </td>
              </tr>
              <tr>
                <td>Your own retrieval code, or its HTTP endpoint</td>
                <td>What comes back for the person asking, before it reaches the prompt</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          The sequence below is the full path a call takes when all four are connected.
          Three of its eight steps can end a call before it reaches anything.{" "}
          <Link href="/docs/connect">The calls themselves are in the docs.</Link>
        </p>

        {/* The same request, at whichever stage you are reading about. The panel
            advances with you; without JavaScript it shows the completed record,
            which is what the static version showed. See follow.tsx. */}
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
                      <span className="mk-mono">amount: 5000   to: acct_x</span>
                    </li>
                    <li className="seq-row seq-row-quiet">
                      <span>argument value came from tool_result</span>
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
              body: (
                <>
                  Which agent, and which end user it acts for. An agent quarantined by
                  the kill switch stops here and never reaches a model.
                </>
              ),
              stops: true,
            },
            {
              title: "Answerability",
              body: (
                <>
                  A question outside the agent&rsquo;s declared knowledge boundary gets
                  a templated refusal, and no model call is made.
                </>
              ),
              stops: true,
            },
            {
              title: "Retrieval is filtered for the person asking",
              body: <>Documents the end user is not entitled to see never reach the prompt.</>,
            },
            {
              title: "Every piece of text is tagged with where it came from",
              body: (
                <>
                  User, retrieved document, tool result, subagent, memory — and whether
                  that source is trusted. Step 6 reads the tag, which is why it still
                  works after step 5 has failed.
                </>
              ),
            },
            {
              title: "Detectors read the text",
              body: (
                <>
                  Each under a time budget, worst verdict carried forward. This is the
                  layer we trust least, and we{" "}
                  <Link href="/benchmark">publish how well it does</Link> — including
                  where a competing scanner is more precise than ours.
                </>
              ),
            },
            {
              title: "Before a tool runs, the action itself is checked",
              body: (
                <>
                  It reads no text. It asks whether the agent holds a grant for the
                  tool, whether argument values are inside the declared ceilings, where
                  those arguments came from, and whether the tool is irreversible. An
                  irreversible call built out of untrusted content is refused, or sent
                  to a person to approve, even when nothing flagged the prompt.
                </>
              ),
              stops: true,
              keystone: true,
            },
            {
              title: "What comes back is checked too",
              body: (
                <>
                  An output pass checks the response for things like PII, and the answer
                  is bound to its sources.
                </>
              ),
            },
            {
              title: "Everything lands in a record you can verify",
              body: (
                <>
                  A trace of the whole path and an entry in a tamper-evident audit
                  chain, allowed or blocked, with an independent verifier.
                </>
              ),
            },
          ]}
        />
        </FollowRequest>

        <p>
          Steps 1 to 5 are what most products in this space also do. Step 6 is what the
          design rests on, because an attacker who keeps trying eventually gets past
          step 5. <Link href="/benchmark">The measurements for both are here &rarr;</Link>
        </p>

        <p>
          Those eight steps are the product&rsquo;s runtime. The six areas around
          them — discovery, access, guardrails, evaluation, audit and compliance —
          each have their own screens once you have signed in.{" "}
          <Link href="/product">What each area does &rarr;</Link>
        </p>

<h2 id="limits">What this does not do</h2>
        <ul>
          <li>
            It does not make your agent robust to attack. Detection loses to an
            attacker who is allowed to adapt, ours included, and we measure that against
            ourselves.
          </li>
          <li>
            It does not know anything you have not declared. An irreversible tool
            recorded as read-only is invisible to the check that would have stopped it.
          </li>
          <li>
            It does not grant or revoke access in your own systems. It bounds what an
            agent does with access you already gave it.
          </li>
          <li>
            It does not block anything you have not asked it to block. The policy that
            governs model traffic ships in observe mode: it records what it would have
            done and lets the call through.
          </li>
          <li>
            One exception is on from the first day. A tool that can move money, delete
            something or send an email will not accept an argument that came out of a web
            page, a retrieved document or another tool&rsquo;s output. Those calls stop
            for a human.
          </li>
        </ul>
        <ul>
          <li>
            <strong>Detection is the weakest layer.</strong> 66.7% recall on a held-out
            set, and an attacker who reads the verdict and retries gets 73% of what we do
            catch through. Published, not rounded.
          </li>
          <li>
            <strong>You declare the estate yourself.</strong> There is no Okta connector
            and no DataHub connector. Principals, grants and source tiers live in
            AgentFox. The seams exist; the integrations do not.
          </li>
          <li>
            <strong>Version 0.3, and the gaps are listed in the repository</strong> No single sign-on, one organisation, text
            only. The full list is in the README.
          </li>
        </ul>

        <div className="note-panel">
          <strong>What all of this rests on.</strong> Grants, impact tiers, ceilings and
          downstream triggers are declared by whoever operates the agent, and the checks
          above believe them. A tool recorded as read-only that is not read-only is not
          covered.{" "}
          <a href={REPO} target="_blank" rel="noreferrer">
            The source, the licence and the limits are all in the repository.
          </a>
        </div>

        <div className="mk-row" style={{ marginTop: 28, gap: 10 }}>
          <Link href="/playground" className="mk-btn mk-btn-primary">
            Try it, no account
          </Link>
          <Link href="/benchmark" className="mk-btn mk-btn-outline">
            The numbers, and where a competitor beats us
          </Link>
        </div>
        </article>
      </div>
      </section>
      </main>
      <Footer />
    </div>
  );
}
