import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Compliance: EU AI Act, NIST, OWASP, ATLAS",
  description:
    "EU AI Act, ISO 42001, NIST, SOC 2, OWASP and MITRE ATLAS. 43 controls, scored from what the agent did, not from a form. The mappings are drafts, not legal advice.",
  path: "/frameworks",
});

/**
 * Counted from `packs/compliance/catalog/controls/controls.yaml` rather than typed. The four
 * at 43 are the frameworks every control maps to; the three below it are
 * threat catalogues, which cover the attack surface rather than the
 * management system, so a lower number is the right number and not a gap.
 */
const FRAMEWORKS = [
  { key: "eu-ai-act", name: "EU AI Act", n: 43, what: "High-risk obligations, including logging and human oversight" },
  { key: "iso-42001", name: "ISO/IEC 42001", n: 43, what: "The AI management system" },
  { key: "nist-ai-rmf", name: "NIST AI RMF", n: 43, what: "Govern, map, measure, manage" },
  { key: "soc2", name: "SOC 2", n: 43, what: "The trust criteria an auditor already uses" },
  { key: "owasp-llm", name: "OWASP LLM Top 10", n: 22, what: "Attacks on language models" },
  { key: "owasp-agentic", name: "OWASP Agentic", n: 19, what: "Threats specific to agents that act" },
  { key: "mitre-atlas", name: "MITRE ATLAS", n: 9, what: "Adversary tactics against ML systems" },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="Compliance"
      title={["EU AI Act, NIST,", "OWASP and ATLAS"]}
      lede="43 controls. Standing comes from what the agent did, not from a form. The mappings are drafts, not reviewed by counsel and not legal advice."
      docs="/docs/guides/audit-evidence"
      challenge={
        <p>Usually this is a document describing controls someone believes are in place.</p>
      }
      feature={{
        title: "Seven frameworks, 43 controls",
        lede: "One control set, mapped across them. Every mapping is a draft.",
        body: (
          <div className="fw-grid mk-stagger">
            {FRAMEWORKS.map((f) => (
              <div key={f.key} className="fw">
                <div className="fw-head">
                  <b>{f.name}</b>
                  <span>{f.n}</span>
                </div>
                <span className="fw-bar" aria-hidden>
                  <i style={{ width: `${(f.n / 43) * 100}%` }} />
                </span>
                <p>{f.what}</p>
              </div>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "Status comes from what happened",
          body: <p>Did the rule exist, did it fire, was a detector down, is the chain intact. Nobody ticks a box.</p>,
        },
        {
          title: "Someone else can check the export",
          body: <p>The same package as the audit trail, with a verifier that does not import our code.</p>,
        },
      ]}
      gaps={{
        title: "What this is not",
        body: (
          <p>
            Not a certification. The mappings are an engineering reading of the
            frameworks, labelled as a draft, and a reading can be wrong.
          </p>
        ) }}
      related={["/evidence", "/runtime", "/product"]}
    />
  );
}
