import type { Metadata } from "next";
import Link from "next/link";

import { DocSection, Limits, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { CopyButton } from "@/components/docs/copy";
import { findIntegration, integrationPath } from "@/lib/marketing/integrations";
import { publicPageMetadata } from "@/lib/site";

export function integrationMetadata(slug: string): Metadata {
  const i = findIntegration(slug);
  return publicPageMetadata({ title: i.title, description: i.description, path: integrationPath(slug) });
}

/** One /integrations/<framework> page: what is checked for that framework, from lib/marketing/integrations.ts. */
export function IntegrationPage({ slug }: { slug: string }) {
  const i = findIntegration(slug);
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <h1>
              {i.name} with AgentFox
              <br />
              <span className="lp-muted">what gets checked, and where</span>
            </h1>
            <p className="lp-lead">{i.lead}</p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection id="install" title="Three lines" lead="Everything starts in Watch: nothing is stopped until you switch a library to Block.">
            <figure className="lp-doc-cite">
              <figcaption>Install</figcaption>
              <pre>{i.install}</pre>
              <CopyButton text={i.install} />
            </figure>
          </DocSection>

          <DocSection id="governed" title="What gets checked" lead="Each row is a check that runs in your process, before the thing it checks happens.">
            <Table head={["Checked", "How"]} rows={i.governed.map((cells) => ({ cells }))} />
            <p>
              <strong>Found in the code by </strong>
              <code>agentfox scan</code>
              <strong>:</strong> {i.discovered}. The scan reads the repository and runs nothing, so it works before
              any of the lines above are added.
            </p>
            <Limits items={i.limits} />
            {i.useCases && <Limits label="Where teams use it" items={i.useCases} />}
          </DocSection>

          <DocSection id="next" title="Where to go from here">
            <p className="lp-doc-more">
              <Link href={i.docs.href}>
                {i.docs.label} <Arrow />
              </Link>
              <Link href="/docs/govern">
                Tool access: which tools the agent may call <Arrow />
              </Link>
              <Link href="/benchmark">
                What the checks catch, with their limits <Arrow />
              </Link>
              <Link href="/integrations">
                Every framework <Arrow />
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
