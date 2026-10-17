import Link from "next/link";
import { DecisionCard } from "@/components/marketing/decisions";
import { REPO } from "@/components/marketing/nav";

/**
 * The hero.
 *
 * Split, rather than centred copy above a picture. Two things changed and both came
 * from watching how a stranger reads this page.
 *
 * The headline was twelve words in two sentences, which is a paragraph set at 4.4rem
 * and is read as an obstacle. It is now eight, and says the same thing: the model can
 * be talked into anything, and the permissions it holds cannot.
 *
 * The picture was a tool call printed as JSON. A reader had to parse an argument
 * object before reaching the only part that mattered, which was the verdict at the
 * bottom. It is now a decision record with labelled rows, so the who, the what, the
 * rule and the answer are all legible in about three seconds.
 *
 * Copy comes first in the DOM, so the phone gets the sentence before the picture.
 * The claim in the bold line is checkable: README.md "See it work right now" —
 * `pip install`, then `agentfox init && agentfox demo`, about a second and about five
 * more, offline, no API key. The evidence package is step 12 of that demo
 * (src/agentfox/apps/cli/demo.py:599-635) and ships with a stdlib-only verifier.
 */
export function Hero() {
  return (
    <section style={{ position: "relative", overflow: "hidden" }}>
      <div className="mk-wash" aria-hidden />

      <div className="mk-wrap" style={{ position: "relative", paddingTop: 62, paddingBottom: 18 }}>
        <div className="mk-split">
          <div className="mk-up">
            <span className="mk-eyebrow">For teams running agents in production</span>

            <h1 className="mk-h1 mk-d1" style={{ marginTop: 16 }}>
              Your agent can be fooled. <em>Its grants cannot.</em>
            </h1>

            <p className="mk-lede mk-d2" style={{ margin: "20px 0 0" }}>
              Hidden text in a document can talk an agent into moving money or leaking
              data, so every tool call is checked against what that agent was actually
              given permission to do.
            </p>

            <p style={{ margin: "20px 0 0", fontWeight: 600 }}>
              Two commands and about six seconds after install. Evidence an auditor can
              check without us.
            </p>

            <div className="mk-row mk-d3" style={{ marginTop: 28 }}>
              <Link href="/playground" className="mk-btn mk-btn-primary">
                Try it, no account
              </Link>
              <Link href="/#decisions" className="mk-btn mk-btn-outline">
                See how it works
              </Link>
              <a
                href={REPO}
                target="_blank"
                rel="noreferrer"
                className="mk-btn mk-btn-ghost"
              >
                Read the source
              </a>
            </div>

            <p className="mk-fine mk-d4" style={{ marginTop: 18 }}>
              Runs offline with no API key · One line in Python, or HTTP from any language
            </p>
          </div>

          <div className="mk-up mk-d5" style={{ minWidth: 0 }}>
            <DecisionCard wide />
            {/* The card is the playground's first preset, and decisions.tsx traces every
                value in it back to seed.py and the shipped policy pack. */}
            <p className="mk-fine" style={{ marginTop: 16 }}>
              A support agent, talked into asking for a transfer it was never granted. The
              first preset in the <Link href="/playground">playground</Link>.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
