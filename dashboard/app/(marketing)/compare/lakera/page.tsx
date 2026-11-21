import type { Metadata } from "next";
import Link from "next/link";

import { DocSection, Limits, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Lakera Guard vs AgentFox",
  description:
    "Lakera Guard is a closed, hosted detection API now part of Check Point; AgentFox is an open source control plane you run yourself. What we could not benchmark, and what the choice comes down to.",
  path: "/compare/lakera",
});

/**
 * Lakera could not be benchmarked: it is closed and its terms do not allow the
 * kind of published comparison we run. Every Lakera fact here is from Lakera's
 * documentation or Check Point's announcement, dated, and nothing else.
 */
export default function LakeraPage() {
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <h1>
              Lakera Guard vs AgentFox
              <br />
              <span className="lp-muted">what we could not measure, and what we can say</span>
            </h1>
            <p className="lp-lead">
              We benchmark every guard we can run. Lakera Guard is closed and hosted, so this page is the facts from its
              own documentation next to ours, and the question the choice actually turns on.
            </p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection id="facts" title="The facts side by side" lead="Lakera's column is from docs.lakera.ai and Check Point's announcement of 16 September 2025. Check their current terms before you decide.">
            <Table
              head={["", "Lakera Guard", "AgentFox"]}
              rows={[
                { cells: ["Owner", "Check Point, since its 2025 acquisition of Lakera", "Nometria"] },
                { cells: ["Source", "Proprietary", "Apache-2.0, on GitHub"] },
                { cells: ["Where it runs", "Lakera's cloud, or self-hosted in your VPC on enterprise terms", "Your machine or cluster; no egress by default"] },
                { cells: ["Price", "By quote", "Free to self-host; hosted version with a free tier"] },
                { cells: ["What it is", "A detection API: prompts and agent traffic in, a verdict out", "Detection, plus tool calls bounded by capability grants, plus a hash-chained audit trail"] },
                { cells: ["Published benchmarks", "Vendor materials", "Scripts, results files and losses at /benchmark"] },
              ]}
            />
          </DocSection>

          <DocSection id="difference" title="The difference that matters" lead="Both detect prompt injection. Only one of them does something when detection fails.">
            <p>
              A detection API answers one question per request: is this text an attack. That is useful, and it is also
              beatable: against an attacker who adapts, published detectors fail more than 90% of the time, and ours is no
              exception. AgentFox is built for the moment after that. Each agent declares what tools and arguments it may
              use, text that arrived from outside cannot reach a privileged parameter, and the call an injection asks for
              is refused whether or not a detector noticed the injection. On AgentDojo&apos;s 588 attacks that holds with
              every detector switched off.
            </p>
            <p>
              Those are our numbers against our own detectors, not against Lakera&apos;s. Lakera&apos;s detection may well
              be better than ours. The point is what happens when any detector, theirs or ours, misses.
            </p>
            <p className="lp-doc-more">
              <Link href="/benchmark">
                Containment with the detectors off, with its limits <Arrow />
              </Link>
            </p>
          </DocSection>

          <DocSection id="pick" title="Which one" lead="Honest version.">
            <Table
              head={["Pick Lakera Guard if", "Pick AgentFox if"]}
              rows={[
                { cells: ["You want a managed service with a vendor on the hook and no infrastructure to run", "You cannot send prompts or tool outputs to a third party, or need to run offline"] },
                { cells: ["You are already in the Check Point estate", "You need the source, an OSI licence, or to self-host without a quote"] },
                { cells: ["Detection on a chat surface is the whole requirement", "Your agents call tools and you have to show what each was allowed to do"] },
                { cells: ["Procurement prefers an enterprise contract", "An auditor has to verify the record without trusting you"] },
              ]}
            />
            <Limits
              items={[
                "Lakera Guard was not benchmarked. Nothing on this page compares its detection to ours, because we could not run it under terms that allow publishing the result.",
                "Lakera's facts are as published on the date above. Pricing, hosting options and ownership can change; check theirs before quoting this page.",
                "'Free tier' refers to our hosted preview; the open core is free to self-host under Apache-2.0.",
              ]}
            />
            <p className="lp-doc-more">
              <Link href="/compare">
                All guardrails compared <Arrow />
              </Link>
              <Link href="/compare/llm-guard">
                LLM Guard vs AgentFox, measured <Arrow />
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
