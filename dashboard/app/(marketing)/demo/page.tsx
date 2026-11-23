import type { Metadata } from "next";
import Link from "next/link";

import { DocSection, Limits, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { SITE_URL, publicPageMetadata } from "@/lib/site";

const VIDEO_ID = "_ofXWW5uK38";
const TITLE = "AgentFox demo: an over-limit payment, a poisoned document and a held call, in 99 seconds";
const DESCRIPTION =
  "A payments agent asked to send $5,000 is refused before the call runs; an instruction hidden in a refund document is stopped before the model reads it; a payment to an account that came out of a tool's output is held for a person, who says no; and the audit chain is verified from exported rows.";

/**
 * The script, from demo/video/agentfox.crossai.flow.yaml in the repository. Every verdict on
 * screen is a real one: the video replays fixed scenarios on a local build, on the real
 * enforcer, with data from `agentfox demo`, and no live model.
 */
const SCENES: [string, string][] = [
  ["An over-limit payment", "A payments agent is asked to send five thousand dollars. The call is refused before it runs, and AgentFox shows which checks failed."],
  ["A poisoned document", "An instruction hidden inside a refund document is stopped before the model ever reads it."],
  ["The map", "Every agent you run: its model, its tools, its data, and a guardrail on every path."],
  ["The one nobody registered", "A marketing bot quietly running in production shows up as a finding."],
  ["A held call", "The agent tries to pay an account it found in a tool's output, not one you gave it. AgentFox traced that value to the tool output and holds the call for a person."],
  ["The decision", "You say no. The money never moves."],
  ["The audit chain", "Every decision is written to a hash chain with signed checkpoints, which you can re-verify from the exported rows."],
  ["The proof", "With every detector switched off, it still contains eight of eight scripted attacks and all 588 AgentDojo attack pairs. The cost is real: only 24 of 97 benign AgentDojo tasks finish without asking a person."],
];

export const metadata: Metadata = publicPageMetadata({
  title: "AgentFox demo in 99 seconds",
  description: DESCRIPTION,
  path: "/demo",
});

function VideoJsonLd() {
  const video = {
    "@context": "https://schema.org",
    "@type": "VideoObject",
    "@id": `${SITE_URL}/demo#video`,
    name: TITLE,
    description: DESCRIPTION,
    thumbnailUrl: [`https://i.ytimg.com/vi/${VIDEO_ID}/maxresdefault.jpg`, `https://i.ytimg.com/vi/${VIDEO_ID}/hqdefault.jpg`],
    uploadDate: "2026-11-03",
    duration: "PT1M39S",
    embedUrl: `https://www.youtube-nocookie.com/embed/${VIDEO_ID}`,
    contentUrl: `https://www.youtube.com/watch?v=${VIDEO_ID}`,
    url: `${SITE_URL}/demo`,
    inLanguage: "en",
    isFamilyFriendly: true,
    transcript: SCENES.map(([, line]) => line).join(" "),
    publisher: { "@id": `${SITE_URL}/#organisation` },
    about: { "@id": `${SITE_URL}/#software` },
  };
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(video) }} />;
}

export default function DemoPage() {
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <VideoJsonLd />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <h1>
              The demo
              <br />
              <span className="lp-muted">99 seconds, every verdict real</span>
            </h1>
            <p className="lp-lead">
              An over-limit payment refused, a poisoned document stopped, a payment to an account the agent found in a
              tool&apos;s output held for a person, and the audit chain verified. Replayed on the real enforcer, with no
              live model.
            </p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection id="watch" title="Watch">
            <div className="lp-doc-video">
              <iframe
                src={`https://www.youtube-nocookie.com/embed/${VIDEO_ID}`}
                title={TITLE}
                loading="lazy"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                referrerPolicy="strict-origin-when-cross-origin"
                allowFullScreen
              />
            </div>
          </DocSection>

          <DocSection id="scenes" title="What happens in it" lead="The script, scene by scene. Each verdict on screen is the enforcer's own.">
            <Table head={["Scene", "What you see"]} rows={SCENES.map((cells) => ({ cells }))} />
            <Limits
              items={[
                "The video replays fixed scenarios on a local build with data from `agentfox demo`; no live model is called.",
                "The compliance view at the end is part of the enterprise edition and its mappings are marked Draft in the product.",
                "The two benchmark numbers are from the public benchmark report, where their scripts and limits are.",
              ]}
            />
          </DocSection>

          <DocSection id="next" title="Try the same things yourself">
            <p className="lp-doc-more">
              <Link href="/playground">
                Send the same attacks to a running agent, no account <Arrow />
              </Link>
              <Link href="/benchmark">
                The 8 of 8 and 588 of 588, with their cost <Arrow />
              </Link>
              <Link href="/docs/quickstart">
                Install it: one command, then one line <Arrow />
              </Link>
            </p>
          </DocSection>
        </div>

        <LpCta />
      </main>
      <LpFooter />
    </div>
  );
}
