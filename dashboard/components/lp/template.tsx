import type { Metadata } from "next";
import Link from "next/link";

import { DocSection, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav, MomentPath } from "@/components/lp/parts";
import { CopyButton } from "@/components/docs/copy";
import { VERDICT_LABEL, findTemplate, templatePath, toolRows, type TemplateCall } from "@/lib/marketing/templates";
import { publicPageMetadata } from "@/lib/site";

export function templateMetadata(slug: string): Metadata {
  const t = findTemplate(slug);
  return publicPageMetadata({ title: t.title, description: t.description, path: templatePath(slug) });
}

/** `tool(key="value", n=1)`, the way /openclaw writes a call. */
const callText = (c: TemplateCall) =>
  `${c.tool}(${Object.entries(c.arguments).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})`;

/** One /templates/<agent> page, from lib/marketing/templates.json. */
export function TemplatePage({ slug }: { slug: string }) {
  const t = findTemplate(slug);
  const policy = t.policy.join("\n");
  const { attack } = t;
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <h1>
              {t.name} template
              <br />
              <span className="lp-muted">its tools, its policy, the attack it stops</span>
            </h1>
            <p className="lp-lead">{t.lead}</p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection id="tools" title="The tools" lead="What each tool can do, and what the agent was granted.">
            <Table
              head={["Tool", "Impact", "Grant"]}
              rows={toolRows(t.policy).map((r) => ({ cells: [<code key="t">{r.tool}</code>, r.impact, r.grant] }))}
            />
          </DocSection>

          <DocSection
            id="policy"
            title="The policy"
            lead="These lines are the whole policy. Anything not granted is refused once tool containment blocks, which the last line turns on."
          >
            <figure className="lp-doc-cite">
              <figcaption>Run against your AgentFox database</figcaption>
              <pre>{policy}</pre>
              <CopyButton text={policy} />
            </figure>
          </DocSection>

          <DocSection id="attack" title="The attack it stops" lead={attack.story}>
            <MomentPath
              steps={[
                { step: "The agent reads", tag: "untrusted", tagClass: "is-warn", text: attack.untrusted },
                { step: "The agent calls a tool", code: true, text: callText(attack) },
                {
                  step: "AgentFox checks the call",
                  tag: VERDICT_LABEL[attack.verdict].toLowerCase(),
                  tagClass: "is-bad",
                  text: `Decided by the rule ${attack.rule}.`,
                },
              ]}
              label={`An attack on the ${t.name.toLowerCase()}`}
              note="Each verdict on this page is what AgentFox returned when the policy above was run and the call was put through it. A test replays them on every change."
            />
            <Table
              head={["Call", "Verdict", "Rule"]}
              rows={t.calls.map((c) => ({
                cells: [<code key="c">{callText(c)}</code>, VERDICT_LABEL[c.verdict], c.rule ? <code key="r">{c.rule}</code> : "none"],
              }))}
            />
          </DocSection>

          <DocSection id="run" title="Run it">
            <p className="lp-doc-more">
              <Link href="/docs/quickstart/cli">
                Install AgentFox and run this policy locally <Arrow />
              </Link>
              <Link href="/playground">
                Send attacks to a running agent in the browser, no account <Arrow />
              </Link>
              <Link href={t.docs.href}>
                {t.docs.label} <Arrow />
              </Link>
              <Link href="/templates">
                Every template <Arrow />
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
